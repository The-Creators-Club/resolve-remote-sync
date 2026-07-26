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
# Upgrade-channel addition: called with the PARSED report response after
# every successful post (the dashboard piggybacks its `upgrade`
# advertisement on the report reply -- see upgrade.py). Exceptions are
# swallowed here so a broken consumer can't take the report loop down.
OnReportResponseFn = Callable[[Any], None]

# First post happens shortly after start() so a freshly-launched companion
# shows up on the dashboard quickly, rather than waiting a full interval.
INITIAL_DELAY_SECONDS = 2.0


def default_http_post(url: str, data: dict, headers: dict, timeout: float) -> Any:
    body = json.dumps(data).encode("utf-8")
    # NOTE: urllib.request title-cases every outgoing header name in
    # AbstractHTTPHandler.do_open() regardless of the casing passed in here
    # (e.g. "X-CCSync-Token" is sent on the wire as "X-Ccsync-Token"). HTTP
    # header names are case-insensitive (RFC 7230 3.2), so this is harmless,
    # but it's a hard stdlib limitation, not something this function
    # controls -- do not "fix" the casing here, it won't stick.
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        get_editor_name: Optional[GetEditorNameFn] = None,
        get_identity_token: Optional[GetIdentityTokenFn] = None,
        on_report_response: Optional[OnReportResponseFn] = None,
        get_transport_health: Optional[Callable[[], dict[str, Any]]] = None,
        get_completions: Optional[Callable[[], list]] = None,
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
            payload["queue"] = list(queue)
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
        return payload

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

        url = f"{self.dashboard_url.rstrip('/')}/api/v1/report"
        headers = {"Content-Type": "application/json"}
        if self.dashboard_token:
            headers["X-CCSync-Token"] = self.dashboard_token
        if self._get_identity_token is not None:
            try:
                identity_token = self._get_identity_token()
            except Exception:
                log.exception("get_identity_token() failed")
                identity_token = None
            if identity_token:
                headers["X-CCSync-Identity"] = identity_token

        payload = self._build_payload(light=light, editor_name=editor_name)
        # A FULL report carries local_manifest + media_tree: a 2000-clip
        # project's media tree plus the per-file manifest cannot cross any
        # real WAN link in 5 s, so those two sections never reached the
        # dashboard at all -- one WARNING for the whole streak, then DEBUG
        # forever (AUDIT_2 CORE-M12). Light ticks keep the short timeout,
        # which is what makes live transfer progress feel responsive.
        timeout = self.timeout if light else self.full_report_timeout
        resp = self._http_post(url, payload, headers, timeout)
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
