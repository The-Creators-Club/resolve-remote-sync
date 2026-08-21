"""Dashboard reporter — a fault-isolated daemon thread that periodically
POSTs this companion's lane statuses to a server-side dashboard, so an
admin can see editor health without remoting in (addition; not in
SPEC.md's config list).

Entirely optional: when `dashboard_url` is blank, start() is a no-op and no
thread is ever created. Any failure while posting (network error, bad
response, whatever) is caught and logged -- it must never affect the sync
lanes or propagate out of the reporter thread.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import config as config_mod
from . import upgrade as upgrade_mod
from .sync.base import STATE_SYNCING, LaneStatus

log = logging.getLogger("ccsync.reporter")

GetStatusesFn = Callable[[], list[LaneStatus]]
HttpPostFn = Callable[[str, dict, dict, float], Any]
# Managed-mode addition: (queue_slugs, current_slug_or_none) -- see
# sync/sequencer.py's `queue_slugs` / `current_slug` properties. None when
# not in managed mode (the reporter payload then omits "queue"/
# "current_project" entirely).
GetQueueInfoFn = Callable[[], tuple[list[str], Optional[str]]]
# Managed-mode addition: the currently open Resolve project name (see
# watcher.TimelineWatcher.last_resolve_project), or None when Resolve is
# closed/unreachable. When supplied, the reporter payload gains a top-level
# "resolve_project" field so the server can do sticky destination-root
# matching -- see selection.py's get_project_roots().
GetResolveProjectFn = Callable[[], Optional[str]]
# Local disk media manifest (manifest.ManifestCache.get) -- see manifest.py.
# HEAVY ticks only.
GetLocalManifestFn = Callable[[], dict[str, Any]]
# Resolve media-pool BIN tree (app.CompanionApp.get_media_tree) -- see
# app.py's docstring on the media_tree keying decision. HEAVY ticks only.
GetMediaTreeFn = Callable[[], dict[str, Any]]
# Machine role ("base" | "editor") -- see config.py's `mode` key.
GetModeFn = Callable[[], str]
# Verified editor identity (addition; see identity.py). When supplied,
# overrides the payload's "editor_name" (raw cfg["editor_name"] is only used
# as the fallback when this getter is absent -- see identity.py's
# require_login gating). Returning None means "no verified identity yet" --
# post_once SKIPS the cycle entirely rather than reporting under a bogus
# name (see post_once).
GetEditorNameFn = Callable[[], Optional[str]]
# The signed identity token (identity.py's IdentityManager.token) sent as
# the "X-CCSync-Identity" header, in addition to the existing
# "X-CCSync-Token" dashboard_token header. None when not signed in --
# omitted entirely (no header) rather than sent empty.
GetIdentityTokenFn = Callable[[], Optional[str]]
# Missing-proxy coverage (app.CompanionApp.proxy_coverage -> proxy_gen.py).
# Which of this machine's originals have no proxy beside them, i.e. which of
# them lane B can never carry to anybody else. A cached, zero-I/O read, so
# unlike local_manifest/media_tree this rides EVERY tick (light ones too) --
# it is a handful of integers, and "nobody else can see this footage" is
# exactly the kind of thing an admin should not have to wait a heavy cycle
# to learn.
GetProxyCoverageFn = Callable[[], dict[str, Any]]
# YouTube auto-import state (app.CompanionApp.youtube_import_status ->
# youtube_import.py): whether the clips the dashboard downloaded have made it
# into the editor's Resolve bins yet. Cached and zero-I/O like the proxy
# coverage above, so it rides every tick -- the dashboard page that started
# the download is watching for exactly this, and a heavy-cycle wait would
# make a working import look like a stuck one.
GetYoutubeImportFn = Callable[[], dict[str, Any]]
# B-roll ingest state (app.CompanionApp.broll_ingest_status ->
# broll_ingest.py): which batch this machine is crunching, how far in, and the
# VRAM refusal if there is one. Scalars only and cached/zero-I/O like the two
# above, so it rides EVERY tick: the page that started the batch is polling for
# exactly this, and the fleet grid's chip is how an admin sees which machines
# are indexing (BROLL_INGEST_PLAN.md §1 step 8, 2026-08-18).
GetBrollIngestFn = Callable[[], dict[str, Any]]
# Music ingest state (app.CompanionApp.music_ingest_status ->
# music_ingest.py): the same shape with `kind: "music"`, and a SECOND section
# rather than a reuse of the one above, because the two run at the same time
# -- music needs no GPU, so a machine can be embedding an album while it
# indexes a camera card, and one section could only ever describe one of them
# (docs/MUSIC_INGEST_PLAN.md 2, 2026-08-18).
GetMusicIngestFn = Callable[[], dict[str, Any]]
# Upgrade-channel addition: called with the PARSED report response after
# every successful post (the dashboard piggybacks its `upgrade`
# advertisement on the report reply -- see upgrade.py). Exceptions are
# swallowed here so a broken consumer can't take the report loop down.
OnReportResponseFn = Callable[[Any], None]

# First post happens shortly after start() so a freshly-launched companion
# shows up on the dashboard quickly, rather than waiting a full interval.
INITIAL_DELAY_SECONDS = 2.0

# The dashboard refuses a report body over 8 MiB outright (413, from
# app.MAX_REPORT_BODY_BYTES) -- and that refusal costs the WHOLE report:
# lane status, transfers, machine_state, presence and the upgrade
# advertisement all go with it. Nothing here measured the payload at all, so
# 64 projects x 2 file lists x 2000 entries sailed straight past the limit and
# the machine went dark on the fleet grid (KNOWN_BUGS B6).
#
# The budget is the server's ceiling minus room for JSON overhead and headers.
# _fit_payload sheds the heavy sections in order of least value until the body
# fits; the lane/status core of the report is never shed, because a report
# that arrives with no presence data is worth far more than one that never
# arrives.
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
PAYLOAD_BUDGET_BYTES = 7 * 1024 * 1024
# Mirror of dashboard api.MAX_REPORT_PROJECTS -- keys in local_manifest /
# media_tree / queue. The server truncates past this; sending fewer keeps the
# choice of WHICH projects survive on this side, where the selection is known.
MAX_REPORT_PROJECTS = 64

# How stale an UNCHANGED local_manifest/media_tree may get before it is sent
# again anyway (ops-efficiency-1, 2026-08-21). The two sections are rebuilt
# on their own schedules (manifest 300 s, media tree 120 s) but the report
# goes out every 60 s, so 4 of every 5 manifest sends were byte-identical to
# the one before -- and the dashboard answers each with a DELETE + INSERT of
# up to 2000 rows per ticked project plus 4000 media-tree rows, on the NAS,
# retained by every hourly snapshot. An absent key already means "leave that
# table alone" on the server (api.py's report handler says so), so the
# unchanged send buys nothing.
#
# The periodic full resend is what makes this safe rather than clever: a
# dashboard restored from backup, a row pruned by MEDIA_REPORT_MAX_AGE_DAYS,
# or a report the server truncated all converge within one window, without
# this side having to know any of it happened.
SECTION_RESEND_SECONDS = 600.0
# Sections that may be omitted when unchanged. Nothing else is ever skipped:
# the lane/status core, the guard block and the ingest sections are either
# tiny or load-bearing by their ABSENCE (an absent broll_ingest means "the
# batch finished").
OMITTABLE_SECTIONS = ("local_manifest", "media_tree")

# How often the reporter re-reads this machine's own Syncthing device id
# (comp-lane-c-3, 2026-08-21). One loopback GET; the id only changes when
# Syncthing's home is regenerated under a running companion.
DEVICE_ID_REFRESH_SECONDS = 300.0


def _section_digest(value: Any) -> str:
    """A stable digest of one report section, or "" when it cannot be taken.

    "" never compares equal to a stored digest, so a section that will not
    serialize here is simply always sent -- the same direction every other
    guard in this file fails."""
    try:
        return hashlib.sha1(
            json.dumps(value, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError):
        return ""


class _MeasuredPayload(dict):
    """A report body that carries the JSON bytes _fit_payload already built
    to measure it.

    Still a plain dict to every injected HttpPostFn (the tests' doubles
    included) -- only default_http_post below knows to reuse `encoded`, so
    the seam is unchanged. Exists because the heavy tick serialised a
    multi-MB local_manifest + media_tree once to size it, threw that away,
    and then dumped the identical structure again inside default_http_post:
    2x CPU and 2x transient peak memory every 60 s, on the base rig that is
    also running the proxy encoder and the b-roll indexer (COMP-CORE-5,
    2026-08-14).
    """

    __slots__ = ("encoded",)


def _encode_payload(payload: dict[str, Any]) -> Optional[bytes]:
    """The report body as JSON bytes, or None when it won't serialize (which
    is the http_post's problem to report, not this guard's)."""
    try:
        return json.dumps(payload).encode("utf-8")
    except (TypeError, ValueError):
        return None


def _measured(payload: dict[str, Any], body: Optional[bytes]) -> dict[str, Any]:
    """Hand `payload` back with its already-serialized `body` attached."""
    if body is None:
        return payload
    carrier = _MeasuredPayload(payload)
    carrier.encoded = body
    return carrier


def payload_size(payload: dict[str, Any]) -> int:
    """Serialized size of the report body, or 0 if it can't be measured (a
    payload that won't serialize is the http_post's problem, not this
    guard's)."""
    body = _encode_payload(payload)
    return len(body) if body is not None else 0


def default_http_post(url: str, data: dict, headers: dict, timeout: float) -> Any:
    # Reuse the bytes _fit_payload already produced when it measured this
    # body against PAYLOAD_BUDGET_BYTES (COMP-CORE-5). Anything else -- light
    # ticks, identity.py's verify POST, a caller passing a plain dict -- takes
    # the normal path.
    body = getattr(data, "encoded", None)
    if not isinstance(body, bytes):
        body = json.dumps(data).encode("utf-8")
    # NOTE: urllib.request title-cases every outgoing header name in
    # AbstractHTTPHandler.do_open() regardless of the casing passed in here
    # (e.g. "X-CCSync-Token" is sent on the wire as "X-Ccsync-Token"). HTTP
    # header names are case-insensitive (RFC 7230 3.2), so this is harmless,
    # but it's a hard stdlib limitation, not something this function
    # controls -- do not "fix" the casing here, it won't stick.
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    # NO REDIRECTS. `headers` carries X-CCSync-Token and X-CCSync-Identity, and
    # urllib.request.urlopen follows 3xx automatically while stripping only the
    # Authorization header -- custom ones ride along. A dashboard (or anything
    # answering in its place) replying "302 Location: http://elsewhere/" would
    # therefore hand this fleet's credentials to another origin, and the
    # companion would parse whatever came back as its report response. The
    # upgrade channel has refused redirects since AUDIT_3 H-1; every other
    # dashboard call does now too (COMMERCIAL_READINESS.md item 15,
    # 2026-08-17). A 3xx surfaces as an HTTPError, which every caller here
    # already treats as a failed request.
    with upgrade_mod.build_no_redirect_opener().open(req, timeout=timeout) as resp:
        resp_data = resp.read()
    return json.loads(resp_data.decode("utf-8")) if resp_data else {}


class DashboardReporter:
    """Periodically posts lane statuses to `dashboard_url`. Never raises out
    of start()/stop()/post_once() -- failures are logged, not propagated."""

    def __init__(
        self,
        get_statuses: GetStatusesFn,
        cfg: dict[str, Any],
        http_post: Optional[HttpPostFn] = None,
        timeout: float = 5.0,
        get_queue_info: Optional[GetQueueInfoFn] = None,
        get_resolve_project: Optional[GetResolveProjectFn] = None,
        get_local_manifest: Optional[GetLocalManifestFn] = None,
        get_media_tree: Optional[GetMediaTreeFn] = None,
        get_mode: Optional[GetModeFn] = None,
        get_machine_id: Optional[Callable[[], str]] = None,
        get_syncthing_device_id: Optional[Callable[[], str]] = None,
        get_editor_name: Optional[GetEditorNameFn] = None,
        get_identity_token: Optional[GetIdentityTokenFn] = None,
        on_report_response: Optional[OnReportResponseFn] = None,
        get_transport_health: Optional[Callable[[], dict[str, Any]]] = None,
        get_completions: Optional[Callable[[], list]] = None,
        get_proxy_coverage: Optional[GetProxyCoverageFn] = None,
        get_youtube_import: Optional[GetYoutubeImportFn] = None,
        get_sync_guard: Optional[Callable[[], dict[str, Any]]] = None,
        get_broll_ingest: Optional[GetBrollIngestFn] = None,
        get_music_ingest: Optional[GetMusicIngestFn] = None,
    ) -> None:
        self._get_statuses = get_statuses
        self.cfg = cfg
        self._http_post = http_post or default_http_post
        self.timeout = timeout
        # Scaled ceiling for the heavy manifest/media-tree sections -- see
        # post_once(). Config-overridable so a very large fleet can tune it.
        try:
            self.full_report_timeout = max(timeout, float(cfg.get("report_timeout_full", 30.0)))
        except (TypeError, ValueError):
            self.full_report_timeout = max(timeout, 30.0)
        self._get_queue_info = get_queue_info
        # Drains the lanes' completed-file events (dashboard HISTORY).
        # DRAIN semantics: events fetched here are gone from the lane, so a
        # failed POST loses that tick's entries -- acceptable for a history
        # feed, never for anything stronger.
        self._get_completions = get_completions
        self._get_resolve_project = get_resolve_project
        self._get_local_manifest = get_local_manifest
        self._get_media_tree = get_media_tree
        self._get_mode = get_mode
        # WP1: both are cached forever after the first success. The id is a
        # file read and the device id an HTTP call to the local Syncthing, and
        # neither changes while this process lives -- a report every 30 s must
        # not pay for either more than once.
        self._get_machine_id = get_machine_id
        self._get_syncthing_device_id = get_syncthing_device_id
        self._machine_id_cache: Optional[str] = None
        self._syncthing_device_id_cache: Optional[str] = None
        # Monotonic stamp of the last successful myID read -- see
        # _syncthing_device_id (comp-lane-c-3).
        self._syncthing_device_id_at = 0.0
        # Digest + monotonic stamp of the last local_manifest / media_tree
        # section this reporter actually got ACCEPTED by the dashboard, so an
        # unchanged one is not re-sent every minute (ops-efficiency-1).
        self._section_state: dict[str, tuple[str, float]] = {}
        # Which sections THIS build left out as unchanged (see
        # _note_sections_sent -- omitted and shed have to be told apart).
        self._omitted_sections: set[str] = set()
        # Who the last report went out as, so a sign-in as a different editor
        # invalidates the section bookkeeping above.
        self._last_reported_editor: Optional[str] = None
        self._get_editor_name = get_editor_name
        self._get_identity_token = get_identity_token
        self._on_report_response = on_report_response
        # Connection-path + orphan diagnostics (AUDIT_2 C-6). Nothing in
        # production could tell a RELAYED editor from a merely slow one:
        # Syncthing devices are added with addresses:["dynamic"] and relays
        # left at their `true` default, so lane C can silently ride the
        # public relay pool at 1-5 MB/s. Same for orphaned .partial uploads,
        # which lane A never deletes and nothing ever reported.
        self._get_transport_health = get_transport_health
        # Optional like every getter here: a companion whose proxy generator
        # failed to construct still reports everything else, with the section
        # simply absent (the dashboard ignores unknown keys and cannot miss
        # one it never knew about -- api.py:2187, extra="ignore").
        self._get_proxy_coverage = get_proxy_coverage
        # Optional on the same terms: absent, or an empty dict from a
        # companion whose importer failed to construct, simply omits the
        # section rather than reporting a zeroed one.
        self._get_youtube_import = get_youtube_import
        # The lane B circuit breaker, the trash size, the sync halt and lane
        # A's "skipped, exists" counter (COMMERCIAL_READINESS.md item 9,
        # 2026-08-17). On EVERY tick including light ones, and NEVER shed by
        # _fit_payload: it is a few hundred bytes, and it is the one section
        # whose absence would leave a machine that has stopped syncing looking
        # exactly like one that has nothing to do.
        self._get_sync_guard = get_sync_guard
        # Optional on the same terms as the two above: an empty dict from a
        # companion with no orchestrator (or one with nothing to say) omits
        # the section, which is how a FINISHED batch is spelled -- the
        # dashboard reads an absent section as "not indexing" and clears the
        # chip (api.flatten_broll_ingest).
        self._get_broll_ingest = get_broll_ingest
        # Optional on exactly the same terms, and omitted-when-empty for the
        # same load-bearing reason: an absent section is how a FINISHED music
        # batch is spelled (api.flatten_music_ingest).
        self._get_music_ingest = get_music_ingest

        self.dashboard_url = str(cfg.get("dashboard_url", "")).strip()
        self.dashboard_token = str(cfg.get("dashboard_token", "")).strip()
        # coerce_numeric, not float(): the reporter is constructed inside
        # CompanionApp.__init__, so a hand-edited
        # `dashboard_report_interval = "1m"` raised there -- the windowed exe
        # exiting with no tray and no log line (AUDIT_2 CORE-M4's family).
        # validate_config() reports the bad value.
        self.report_interval = config_mod.coerce_numeric(cfg, "dashboard_report_interval", 60)
        # Adaptive cadence: while any lane is actively syncing, report more
        # often (dashboard_report_interval_active) -- but the heavier
        # local_manifest/media_tree payload sections still only go out at
        # most every report_interval seconds (see _run_cycle).
        self.report_interval_active = config_mod.coerce_numeric(
            cfg, "dashboard_report_interval_active", 5
        )

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Fault-isolation logging state: WARNING on the first failure of a
        # streak, DEBUG for repeats, reset to WARNING-eligible on success --
        # mirrors the "warn once" pattern in watcher.py without spamming the
        # log every interval while the dashboard is unreachable.
        self._error_logged = False
        # monotonic timestamp of the last HEAVY (light=False) post ATTEMPT
        # -- 0.0 forces the very first tick to be heavy regardless of
        # cadence. Set on attempt, not only on success (see _run_cycle):
        # a heavy payload that times out must still degrade to the normal
        # report_interval cadence instead of retrying the full
        # local_manifest/media_tree payload on every fast active tick
        # forever.
        self._last_heavy_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.dashboard_url)

    def _machine_id(self) -> Optional[str]:
        """This computer's minted id, or None when this build/machine has
        none. Cached: it is a file read that cannot change under us, and the
        empty answer is cached too so a read-only home directory is not
        re-tried every 30 seconds."""
        if self._machine_id_cache is None:
            value = ""
            if self._get_machine_id is not None:
                try:
                    value = str(self._get_machine_id() or "")
                except Exception:
                    log.exception("get_machine_id() failed")
            self._machine_id_cache = value
        return self._machine_id_cache or None

    def _syncthing_device_id(self) -> Optional[str]:
        """This machine's own Syncthing device ID, or None while Syncthing is
        not answering. NOT cached negatively for the process lifetime: lane C
        supervision restarts Syncthing, and the first few reports of a run can
        legitimately land before it is up.

        Nor cached POSITIVELY for the process lifetime any more
        (comp-lane-c-3, 2026-08-21): `syncthing serve` on a home whose
        key/cert are gone mints a NEW identity, and the supervisor restarting
        a wiped home is the one event that changes myID mid-run -- an event
        this companion causes itself. Reporting the dead id kept the
        dashboard sharing folders with a device that no longer exists (the
        upsert COALESCEs, so a non-null stale value is never replaced) until
        the next tray restart. Re-read on a slow cadence instead: one
        loopback GET every DEVICE_ID_REFRESH_SECONDS. A refresh that comes
        back empty KEEPS the known id -- Syncthing being briefly down is not
        evidence that the id changed."""
        cached = self._syncthing_device_id_cache
        if cached and (time.monotonic() - self._syncthing_device_id_at) < DEVICE_ID_REFRESH_SECONDS:
            return cached
        if self._get_syncthing_device_id is None:
            return None
        try:
            value = str(self._get_syncthing_device_id() or "")
        except Exception:
            log.debug("get_syncthing_device_id() failed", exc_info=True)
            return cached or None
        if value:
            if cached and value != cached:
                log.warning(
                    "this machine's Syncthing device id changed (%s -> %s) -- its "
                    "config must have been regenerated; reporting the new one",
                    cached, value)
            self._syncthing_device_id_cache = value
            self._syncthing_device_id_at = time.monotonic()
        return value or cached or None

    # -- payload -----------------------------------------------------
    def _build_payload(self, light: bool = False, editor_name: Optional[str] = None) -> dict[str, Any]:
        """Build the report payload. LIGHT ticks (light=True) omit
        "local_manifest"/"media_tree" entirely (keys absent) -- everything
        else, including per-lane "transfers", is always included.

        `editor_name`: the resolved name to report under -- passed in by
        post_once (which resolves it via get_editor_name, falling back to
        cfg["editor_name"] when no getter was supplied) rather than read
        from cfg directly here, so post_once's skip-when-unverified logic
        and this payload always agree on identity."""
        if editor_name is None:
            editor_name = self.cfg.get("editor_name", "")
        statuses = self._get_statuses()
        payload: dict[str, Any] = {
            "editor_name": editor_name,
            "machine": platform.node(),
            # WP1 (MULTI_MACHINE_PLAN.md): the hostname is the key the plan
            # hangs on, and an editor can change it in ten seconds. This is
            # what lets the dashboard recognise the same computer afterwards
            # instead of handing it an empty plan. Read through a getter so
            # nothing here touches the disk on a 30 s cadence.
            "machine_id": self._machine_id(),
            # ...and which Syncthing device this machine IS, so a folder can
            # be shared with THIS computer rather than with every device
            # carrying its owner's name.
            "syncthing_device_id": self._syncthing_device_id(),
            "companion_version": config_mod.VERSION,
            "platform": upgrade_mod.platform_key(),
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "lanes": [
                {
                    "name": status.name,
                    "state": status.state,
                    "queued": status.queued,
                    "transferring": status.transferring,
                    "last_error": status.last_error,
                    "last_sync": status.last_sync.isoformat() if status.last_sync else None,
                    "detail": status.detail or None,
                    "current_project": status.current_project,
                    "bytes_done": status.bytes_done,
                    "bytes_total": status.bytes_total,
                    "speed_bps": status.speed_bps,
                    "eta_seconds": status.eta_seconds,
                    "transfers": list(status.transfers),
                }
                for status in statuses
            ],
        }
        if self._get_completions is not None:
            try:
                completed = list(self._get_completions() or [])[:200]
            except Exception:
                log.exception("get_completions() failed")
                completed = []
            if completed:
                payload["completed"] = completed
        if self._get_queue_info is not None:
            try:
                queue, current_project = self._get_queue_info()
            except Exception:
                log.exception("get_queue_info() failed")
                queue, current_project = [], None
            # Capped for the same reason as local_manifest (B6): the server's
            # `queue` field takes at most MAX_REPORT_PROJECTS entries, and it
            # used to reject the whole report over the 65th.
            queue = list(queue)
            if len(queue) > MAX_REPORT_PROJECTS:
                log.warning(
                    "reporting the first %d of %d queued project(s): the dashboard's "
                    "queue field takes no more (B6)", MAX_REPORT_PROJECTS, len(queue))
                queue = queue[:MAX_REPORT_PROJECTS]
            payload["queue"] = queue
            payload["current_project"] = current_project
        if self._get_resolve_project is not None:
            try:
                resolve_project = self._get_resolve_project()
            except Exception:
                log.exception("get_resolve_project() failed")
                resolve_project = None
            payload["resolve_project"] = resolve_project
        if self._get_mode is not None:
            try:
                payload["mode"] = self._get_mode()
            except Exception:
                log.exception("get_mode() failed")
        if self._get_transport_health is not None:
            try:
                payload["transport_health"] = self._get_transport_health()
            except Exception:
                log.exception("get_transport_health() failed")
        if self._get_proxy_coverage is not None:
            try:
                coverage = self._get_proxy_coverage()
            except Exception:
                log.exception("get_proxy_coverage() failed")
                coverage = None
            # An EMPTY dict is omitted, not sent: that is what a companion
            # with no generator returns, and a section of nothing on the wire
            # would be indistinguishable from "this machine has no gaps".
            if coverage:
                projects = coverage.get("projects")
                if isinstance(projects, dict) and len(projects) > MAX_REPORT_PROJECTS:
                    coverage = {**coverage, "projects": dict(
                        list(projects.items())[:MAX_REPORT_PROJECTS]
                    )}
                payload["proxy_coverage"] = coverage
        if self._get_youtube_import is not None:
            try:
                youtube = self._get_youtube_import()
            except Exception:
                log.exception("get_youtube_import() failed")
                youtube = None
            # Empty is omitted, exactly like proxy_coverage above: that is
            # what a companion with no importer returns, and a section of
            # nothing on the wire cannot be told from "nothing to import".
            if youtube:
                payload["youtube_import"] = youtube
        if self._get_sync_guard is not None:
            try:
                guard = self._get_sync_guard()
            except Exception:
                log.exception("get_sync_guard() failed")
                guard = None
            if guard:
                payload["sync_guard"] = guard
        if self._get_broll_ingest is not None:
            try:
                ingest = self._get_broll_ingest()
            except Exception:
                log.exception("get_broll_ingest() failed")
                ingest = None
            # Empty is omitted, like the two sections above -- and here that
            # omission is load-bearing rather than an economy: it is what tells
            # the dashboard the batch is over.
            if ingest:
                payload["broll_ingest"] = ingest
        if self._get_music_ingest is not None:
            try:
                music = self._get_music_ingest()
            except Exception:
                log.exception("get_music_ingest() failed")
                music = None
            if music:
                payload["music_ingest"] = music
        if not light:
            if self._get_local_manifest is not None:
                try:
                    payload["local_manifest"] = self._get_local_manifest()
                except Exception:
                    log.exception("get_local_manifest() failed")
            if self._get_media_tree is not None:
                try:
                    payload["media_tree"] = self._get_media_tree()
                except Exception:
                    log.exception("get_media_tree() failed")
            self._drop_unchanged_sections(payload)
        return payload

    # -- unchanged-section suppression (ops-efficiency-1, 2026-08-21) -----
    def _drop_unchanged_sections(self, payload: dict[str, Any]) -> None:
        """Omit local_manifest/media_tree when they are byte-identical to
        the last one the dashboard ACCEPTED and that was less than
        SECTION_RESEND_SECONDS ago.

        The server contract this leans on is "an absent field leaves that
        table untouched", which is what the report handler already does and
        says. Accepted, not merely built: _note_sections_sent is called after
        a successful POST only, so a failed/timed-out report resends, and a
        section _fit_payload shed is remembered as NOT sent."""
        now = time.monotonic()
        omitted: set[str] = set()
        for key in OMITTABLE_SECTIONS:
            if key not in payload:
                continue
            digest = _section_digest(payload[key])
            if not digest:
                continue
            sent = self._section_state.get(key)
            if sent is None or sent[0] != digest or (now - sent[1]) >= SECTION_RESEND_SECONDS:
                continue
            payload.pop(key)
            omitted.add(key)
            log.debug("report: %s is unchanged since the last accepted report -- omitted", key)
        self._omitted_sections = omitted

    def _note_sections_sent(self, payload: dict[str, Any]) -> None:
        """Remember what the dashboard just accepted, per section.

        Three shapes, and only the first two keep a stamp: the section rode
        this report (record the digest of what actually went, which is the
        FITTED content -- a trimmed manifest must not be mistaken for the
        full one next cycle); it was omitted as unchanged (its existing stamp
        stands, so the forced resend still lands on time); or _fit_payload
        shed it to make the body fit, in which case the dashboard never got
        it and the stamp has to go or the section would be suppressed on the
        strength of a report that dropped it."""
        now = time.monotonic()
        for key in OMITTABLE_SECTIONS:
            if key in payload:
                digest = _section_digest(payload[key])
                if digest:
                    self._section_state[key] = (digest, now)
                else:
                    self._section_state.pop(key, None)
            elif key not in self._omitted_sections:
                self._section_state.pop(key, None)

    def _fit_payload(
        self, payload: dict[str, Any], budget: int = PAYLOAD_BUDGET_BYTES
    ) -> dict[str, Any]:
        """Shed heavy sections until the body fits inside `budget` (B6).

        Least-valuable-first, and each step is logged so a truncated report is
        never silent:

          1. per-file manifest lists  -- the rollup counts/bytes stay exact,
             which is what the fleet grid actually renders;
          2. media_tree clip lists    -- trimmed to a bounded head;
          3. the proxy-coverage per-project map -- the SCALARS survive, which
             is the part that answers "can anyone else see this editor's
             footage"; which project the gap is in is a detail;
          4. project keys             -- the manifest's own priority order
             already put ticked/recent projects first;
          5. the heavy sections entirely -- a LIGHT report that arrives beats
             a HEAVY one that 413s and takes lane status with it.

        Never raises: a payload that cannot be measured is passed through
        untouched (the POST will fail and be retried like any other failure).

        Returns the payload with the JSON bytes of the FINAL measurement
        attached (see _MeasuredPayload) so default_http_post doesn't
        serialize the same multi-MB structure a second time (COMP-CORE-5).
        """
        body = _encode_payload(payload)
        size = len(body) if body is not None else 0
        if size <= budget:
            return _measured(payload, body)

        manifest = payload.get("local_manifest")
        if isinstance(manifest, dict):
            # COPIES, never in-place edits: ManifestCache.get() returns a
            # shallow copy, so its per-project dicts are shared with the live
            # cache -- stripping them here would blank the cached file lists
            # until the next full rescan (manifest_refresh_interval later).
            stripped = 0
            trimmed: dict[str, Any] = {}
            for rel, entry in manifest.items():
                if (isinstance(entry, dict)
                        and (entry.get("originals") is not None
                             or entry.get("proxies") is not None)):
                    entry = {**entry, "originals": None, "proxies": None,
                             "truncated": True}
                    stripped += 1
                trimmed[rel] = entry
            if stripped:
                payload["local_manifest"] = manifest = trimmed
                log.warning(
                    "report payload is %.1f MB (budget %.1f MB): dropped the per-file "
                    "lists from %d project(s); rollup counts are unaffected",
                    size / 1e6, budget / 1e6, stripped)
                body = _encode_payload(payload)
                size = len(body) if body is not None else 0
                if size <= budget:
                    return _measured(payload, body)

        tree = payload.get("media_tree")
        if isinstance(tree, dict) and tree:
            # `tree` is _build_payload's own top-level dict and clips[:500]
            # builds a new list, so nothing the media-tree cache owns is
            # touched here either.
            clips_dropped = 0
            for name, clips in list(tree.items()):
                if isinstance(clips, list) and len(clips) > 500:
                    clips_dropped += len(clips) - 500
                    tree[name] = clips[:500]
            if clips_dropped:
                log.warning("report payload still %.1f MB: trimmed %d media-pool clip(s)",
                            size / 1e6, clips_dropped)
                body = _encode_payload(payload)
                size = len(body) if body is not None else 0
                if size <= budget:
                    return _measured(payload, body)

        coverage = payload.get("proxy_coverage")
        if isinstance(coverage, dict) and coverage.get("projects"):
            # A COPY, like the manifest step above: coverage() hands back a
            # fresh dict per call today, but stripping a section in place is
            # the shape that blanked the live manifest cache once already.
            payload["proxy_coverage"] = {**coverage, "projects": {}, "truncated": True}
            log.warning(
                "report payload still %.1f MB: dropped the per-project proxy gap map; "
                "the totals are unaffected", size / 1e6)
            body = _encode_payload(payload)
            size = len(body) if body is not None else 0
            if size <= budget:
                return _measured(payload, body)

        if isinstance(manifest, dict) and len(manifest) > 1:
            keep = max(1, len(manifest) // 2)
            log.warning("report payload still %.1f MB: reporting %d of %d project(s)",
                        size / 1e6, keep, len(manifest))
            payload["local_manifest"] = dict(list(manifest.items())[:keep])
            body = _encode_payload(payload)
            size = len(body) if body is not None else 0
            if size <= budget:
                return _measured(payload, body)

        for key in ("media_tree", "local_manifest"):
            if payload.get(key) is not None:
                log.warning(
                    "report payload still %.1f MB: dropping %r entirely so the rest of "
                    "the report (lane status, transfers, presence) still reaches the "
                    "dashboard", size / 1e6, key)
                payload.pop(key, None)
                body = _encode_payload(payload)
                size = len(body) if body is not None else 0
                if size <= budget:
                    return _measured(payload, body)
        return _measured(payload, body)

    def post_once(self, light: bool = False) -> None:
        """Build and send a single report. Raises on failure -- callers
        (the report loop) are responsible for fault isolation.

        When `get_editor_name` is supplied and returns None (require_login
        is on and the editor hasn't signed in yet -- see identity.py/
        app.py), the cycle is SKIPPED entirely: no request is made. This is
        what keeps the companion from reporting under a bogus/unverified
        identity."""
        if not self.enabled:
            return

        editor_name: Optional[str] = self.cfg.get("editor_name", "")
        if self._get_editor_name is not None:
            try:
                editor_name = self._get_editor_name()
            except Exception:
                log.exception("get_editor_name() failed")
                editor_name = None
            if editor_name is None:
                log.debug("dashboard report skipped: no verified editor identity")
                return

        if editor_name != self._last_reported_editor:
            # A tray sign-in as somebody else reports the same machine under
            # a new identity, and the dashboard keys media rows on (editor,
            # machine) -- so the new identity's tables are empty and nothing
            # this reporter sent before counts as delivered to them
            # (ops-efficiency-1).
            self._section_state.clear()
            self._last_reported_editor = editor_name

        url = f"{self.dashboard_url.rstrip('/')}/api/v1/report"
        headers = {"Content-Type": "application/json"}
        # Read from cfg per post, not from the value cached at construction:
        # IdentityManager republishes the report token /api/v1/verify hands
        # back into this same dict on sign-in, and a stale config.toml
        # `dashboard_token` otherwise 401s every report forever with a
        # successful tray sign-in sitting right next to it (see identity.py's
        # _adopt_report_token). The cached value is the fallback.
        token = str(self.cfg.get("dashboard_token", "") or "").strip() or self.dashboard_token
        if token:
            headers["X-CCSync-Token"] = token
        if self._get_identity_token is not None:
            try:
                identity_token = self._get_identity_token()
            except Exception:
                log.exception("get_identity_token() failed")
                identity_token = None
            if identity_token:
                headers["X-CCSync-Identity"] = identity_token

        payload = self._build_payload(light=light, editor_name=editor_name)
        if not light:
            # B6: the dashboard 413s a body over MAX_REPORT_BODY_BYTES, and
            # that costs the WHOLE report -- lane status included. Shed the
            # heavy sections until it fits rather than let that happen.
            payload = self._fit_payload(payload)
        # A FULL report carries local_manifest + media_tree: a 2000-clip
        # project's media tree plus the per-file manifest cannot cross any
        # real WAN link in 5 s, so those two sections never reached the
        # dashboard at all -- one WARNING for the whole streak, then DEBUG
        # forever (AUDIT_2 CORE-M12). Light ticks keep the short timeout,
        # which is what makes live transfer progress feel responsive.
        timeout = self.timeout if light else self.full_report_timeout
        resp = self._http_post(url, payload, headers, timeout)
        if not light:
            # AFTER the post: a report that raised never reached the
            # dashboard, so nothing about it may suppress the next one
            # (ops-efficiency-1).
            self._note_sections_sent(payload)
        # The dashboard truncates rather than rejecting an oversized section
        # (B6) and says so in the reply. Log it: "the dashboard is not showing
        # everything this machine has" must be discoverable from this log, not
        # only from the server's.
        try:
            dropped = resp.get("truncated") if isinstance(resp, dict) else None
        except Exception:
            dropped = None
        if dropped:
            log.warning("the dashboard truncated this report: %s", dropped)
            # What the server truncated it does NOT hold, so this report must
            # not be the one that suppresses the next send of it
            # (ops-efficiency-1).
            self._section_state.clear()
        if self._on_report_response is not None:
            try:
                self._on_report_response(resp)
            except Exception:
                log.exception("on_report_response() failed")

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if not self.enabled:
            log.debug("dashboard reporter disabled (dashboard_url is blank)")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._report_loop, name="ccsync-dashboard-reporter", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    # -- adaptive cadence -----------------------------------------------
    def _select_interval(self) -> float:
        """report_interval_active while any lane is actively syncing, else
        the normal report_interval. Factored out from _report_loop so tests
        can exercise the selection logic directly without a real thread."""
        try:
            statuses = self._get_statuses()
        except Exception:
            log.exception("get_statuses() failed while selecting report interval")
            statuses = []
        if any(getattr(status, "state", None) == STATE_SYNCING for status in statuses):
            return self.report_interval_active
        return self.report_interval

    # -- loop -----------------------------------------------------
    def _report_loop(self) -> None:
        if self._stop_event.wait(INITIAL_DELAY_SECONDS):
            return
        while not self._stop_event.is_set():
            interval = self._select_interval()
            # A fast (active) tick sends the lighter payload unless a heavy
            # post hasn't gone out in a full report_interval -- so
            # local_manifest/media_tree still refresh on the dashboard at
            # roughly the normal cadence even while lanes keep this loop
            # ticking fast.
            active_tick = interval == self.report_interval_active
            now = time.monotonic()
            light = active_tick and (now - self._last_heavy_at) < self.report_interval
            self._run_cycle(light=light)
            if self._stop_event.wait(interval):
                break

    def _run_cycle(self, light: bool = False) -> None:
        if not light:
            # Mark the heavy ATTEMPT now, before the post -- not only on
            # success. Otherwise a heavy payload that fails/times out (e.g.
            # a large multi-project local_manifest exceeding `timeout`)
            # never updates this timestamp, so every subsequent active tick
            # keeps computing `light=False` and resends the same oversized
            # payload every report_interval_active seconds forever instead
            # of degrading to the normal cadence.
            self._last_heavy_at = time.monotonic()
        try:
            self.post_once(light=light)
        except Exception as exc:
            if not self._error_logged:
                log.warning("dashboard report failed: %s", exc)
                self._error_logged = True
            else:
                log.debug("dashboard report failed: %s", exc)
        else:
            self._error_logged = False
