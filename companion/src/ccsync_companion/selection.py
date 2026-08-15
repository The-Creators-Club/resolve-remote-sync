"""Dashboard-driven project selection — the server decides WHICH projects
this editor should have synced (server-side unshare is the authority for
unselected projects); this module fetches that ordered list so the
sequencer (sync/sequencer.py) knows what to sync and in what order.

Entirely optional / "managed mode" only: when `dashboard_url` is blank,
`enabled` is False and callers should fall back to legacy (whole-tree,
all-lanes-run-continuously) behavior -- see app.py.

Mirrors reporter.py's shape: a tiny injectable HTTP function, never-raise
fetch(), and once-per-streak failure logging so a flaky/unreachable
dashboard doesn't spam the log every poll.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from . import config as config_mod
from .sync.repath import normalized_safe_rel

log = logging.getLogger("ccsync.selection")

HttpGetFn = Callable[[str, dict, float], Any]
# The signed identity token (identity.py's IdentityManager.token), sent as
# the "X-CCSync-Identity" header exactly as reporter.py sends it on
# /api/v1/report. The dashboard's selection-read endpoint now requires it
# ALONGSIDE the shared X-CCSync-Token -- the fleet-wide token alone no
# longer authorizes reading a given editor's selection. None when not signed
# in: the header is omitted (never sent empty) and the fetch is still
# ATTEMPTED, so an unauthenticated 401 degrades exactly like any other fetch
# failure (cached selection, once-per-streak logging).
GetIdentityTokenFn = Callable[[], Optional[str]]

CACHE_FILENAME = "selection.json"


def default_http_get(url: str, headers: dict, timeout: float) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8")) if data else {}


class SelectionClient:
    """Fetches the dashboard's ordered project selection for this editor,
    with a tolerant on-disk cache so a transient dashboard outage doesn't
    stop syncing entirely (the sequencer keeps working the last-known
    order)."""

    def __init__(
        self,
        cfg: dict[str, Any],
        state_dir: Path,
        http_get: Optional[HttpGetFn] = None,
        timeout: float = 5.0,
        editor_name_fn: Optional[Callable[[], Optional[str]]] = None,
        identity_token_fn: Optional[GetIdentityTokenFn] = None,
    ) -> None:
        self.cfg = cfg
        self.state_dir = state_dir
        self._http_get = http_get or default_http_get
        self.timeout = timeout
        # See GetIdentityTokenFn. Optional so callers that predate the
        # dashboard's identity requirement (and tests) still work; when it is
        # absent the request goes out with the shared token only, which is
        # what the dashboard used to accept.
        self._identity_token_fn = identity_token_fn

        self.dashboard_url = str(cfg.get("dashboard_url", "")).strip()
        # Kept as a fallback only -- see report_token().
        self.dashboard_token = str(cfg.get("dashboard_token", "")).strip()
        # Evaluated per fetch, not just once here -- so a tray sign-in as a
        # verified identity (app.py's editor_identity()) redirects which
        # editor's tick list gets fetched, instead of this staying pinned to
        # whatever editor_name was in config.toml at construction time (see
        # identity.py's docstring: the verified username "becomes this
        # companion's identity for reporting/selection"). Defaults to the
        # raw config value for back-compat / require_login=false callers
        # that never pass one.
        self._editor_name_fn = editor_name_fn or (lambda: cfg.get("editor_name", ""))

        self._cache_path = self.state_dir / CACHE_FILENAME

        # Fault-isolation logging state: WARNING on the first failure of a
        # streak, DEBUG for repeats -- mirrors reporter.py's pattern.
        self._error_logged = False
        # Full last-fetched response (superset of "selection" -- also carries
        # "project_roots", the sticky per-Resolve-project destination
        # mapping -- see get_project_roots()). None until a live fetch
        # succeeds at least once this run.
        self._last_response: Optional[dict[str, Any]] = None
        # Monotonic stamp for the TTLs below.
        self._last_response_at = 0.0
        # Monotonic stamp of the last FAILED attempt (0.0 = none this run),
        # and whose selection it was for. The TTL above is stamped only on
        # success, so with the dashboard unreachable -- container restarting,
        # laptop off the tailnet, rotated token -- every caller fell straight
        # through to a fresh blocking 5 s urlopen. The tray's 2 s refresh tick
        # calls this (app.removable_projects), which is ~12,000 doomed
        # requests a day and an icon/tooltip that lags its own state change
        # (COMP-CORE-3, 2026-08-14).
        self._last_failure_at = 0.0
        self._last_failure_editor: Optional[str] = None
        # How long get()/fetch() may serve the in-memory response without
        # going back to the network. get() used to do a LIVE HTTP fetch (and
        # a disk write) on every call, and the sequencer calls it from a
        # 5-second poll loop: ~120 requests + 120 writes per project per
        # pass per editor, against the dashboard running ON THE NAS, exactly
        # while transfers are in flight (AUDIT_2 P11 / L-5).
        #
        # coerce_numeric, not float(): a hand-edited `selection_fetch_ttl =
        # "30s"` raised here, and SelectionClient is built inside
        # CompanionApp.__init__ -- the windowed exe then dies with no tray and
        # no log line (AUDIT_2 CORE-M4's family). Both keys are in DEFAULTS,
        # the template and validate_config() now.
        self.fetch_ttl = config_mod.coerce_numeric(cfg, "selection_fetch_ttl", 30)
        # Separate, longer TTL for the sticky destination mapping -- see
        # project_roots_result().
        self.project_roots_ttl = config_mod.coerce_numeric(cfg, "project_roots_ttl", 300)
        # Whose selection _last_response holds -- the TTL is keyed on it.
        self._last_response_editor: Optional[str] = None
        # Last payload actually written to disk, for write-only-on-change.
        self._last_written: Optional[dict[str, Any]] = None

    @property
    def enabled(self) -> bool:
        return bool(self.dashboard_url)

    def report_token(self) -> str:
        """The shared fleet token for the X-CCSync-Token header, read from cfg
        PER REQUEST rather than cached at construction.

        /api/v1/verify hands the current report token back at sign-in, and
        identity.IdentityManager republishes it into this same cfg dict -- so
        a config.toml `dashboard_token` that has been rotated on the server
        (or mistyped at install) stops 401-ing every selection fetch the
        moment the editor signs in, instead of forever."""
        return str(self.cfg.get("dashboard_token", "") or "").strip() or self.dashboard_token

    # -- fetch -----------------------------------------------------
    def fetch(self, force: bool = False) -> Optional[list[dict]]:
        """Single synchronous fetch. Never raises -- returns None on any
        failure (network error, bad JSON, unexpected shape).

        Throttled by `fetch_ttl`: a response younger than that is served from
        memory with no request and no disk write (AUDIT_2 P11). `force=True`
        bypasses it for the paths that genuinely want a round trip."""
        if not self.enabled:
            return None
        editor_name = str(self._editor_name_fn() or "").strip().lower()
        # The TTL is keyed on the editor too: a tray sign-in must redirect
        # WHOSE tick list is fetched immediately, not up to fetch_ttl later.
        if (
            not force
            and self._last_response is not None
            and editor_name == self._last_response_editor
            and (time.monotonic() - self._last_response_at) < self.fetch_ttl
        ):
            cached = self._last_response.get("selection")
            if isinstance(cached, list):
                return cached
        if not editor_name:
            # No verified/configured identity yet (e.g. require_login=true
            # and not signed in). Requesting /api/v1/selection/ with no
            # username 404s every single poll forever -- skip the request
            # entirely and let get() fall back to the cache/none, same as
            # any other fetch failure, but without the network round trip
            # or log spam (see the selection-identity finding).
            return None
        # A FAILING dashboard is retried at fetch_ttl too, not on every call
        # (COMP-CORE-3): the throttle above is stamped on success only, so an
        # outage turned every caller into its own 5 s blocking round trip.
        # `force=True` still bypasses it -- the paths that genuinely want a
        # round trip (sign-in, an explicit refresh) are unaffected.
        if (
            not force
            and self._last_failure_at
            and editor_name == self._last_failure_editor
            and (time.monotonic() - self._last_failure_at) < self.fetch_ttl
        ):
            return None
        url = f"{self.dashboard_url.rstrip('/')}/api/v1/selection/{quote(editor_name, safe='')}"
        headers = self._headers()
        try:
            response = self._http_get(url, headers, self.timeout)
            selection = response.get("selection") if isinstance(response, dict) else None
            if not isinstance(selection, list):
                raise ValueError(f"unexpected response shape: {response!r}")
        except Exception as exc:
            if not self._error_logged:
                log.warning("selection fetch failed: %s", exc)
                self._error_logged = True
            else:
                log.debug("selection fetch failed: %s", exc)
            self._last_failure_at = time.monotonic()
            self._last_failure_editor = editor_name
            return None

        self._error_logged = False
        self._last_failure_at = 0.0
        self._last_response = response if isinstance(response, dict) else {"selection": selection}
        self._last_response_at = time.monotonic()
        self._last_response_editor = editor_name
        self._write_cache(self._last_response)
        return selection

    def _headers(self) -> dict[str, str]:
        """Auth headers for a selection read.

        BOTH the shared dashboard token and the signed identity token, the
        same pair /api/v1/report sends: the dashboard's selection endpoint
        now requires X-CCSync-Identity as well, so a fetch carrying only
        X-CCSync-Token 401s and every editor silently falls back to the
        cached selection.

        Never raises and never sends an empty identity header -- the
        not-signed-in case must still ATTEMPT the fetch (an old dashboard
        answers it) and degrade through the existing failure path if it
        doesn't."""
        headers: dict[str, str] = {}
        token = self.report_token()
        if token:
            headers["X-CCSync-Token"] = token
        if self._identity_token_fn is not None:
            try:
                identity_token = self._identity_token_fn()
            except Exception:
                log.debug("selection: identity_token_fn failed", exc_info=True)
                identity_token = None
            if identity_token:
                headers["X-CCSync-Identity"] = str(identity_token)
        return headers

    def _write_cache(self, response: dict[str, Any]) -> None:
        # WRITE ONLY ON CHANGE. This was rewritten on every successful
        # fetch, and fetch() is reached from the sequencer's poll loop --
        # 120 disk writes per project per pass per editor while waiting out a
        # lane C turn, all of them byte-identical (AUDIT_2 P11).
        if response == self._last_written:
            return
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "response": response,
            }
            # tmp + replace, like identity.save_identity. A bare write_text
            # truncates first, and this path is rewritten from inside the
            # sequencer's 5-second poll loop -- a companion killed at that
            # instant left a ZERO-BYTE selection.json, so load_cached()
            # returned None and the next start with the dashboard down meant
            # STATE_NO_SELECTION and lanes A/B never ran (AUDIT_2 §2-low).
            tmp = self._cache_path.with_name(self._cache_path.name + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._cache_path)
            self._last_written = response
        except Exception:
            log.debug("failed to write selection cache to %s", self._cache_path, exc_info=True)

    # -- cache -----------------------------------------------------
    def _load_cached_response(self) -> Optional[dict[str, Any]]:
        """Tolerant read of the on-disk cache's full response. Never raises
        -- returns None on any failure (missing file, malformed JSON,
        unexpected shape). Tolerates the older cache format written before
        the full response was cached (just {"fetched_at", "selection"})."""
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        response = data.get("response")
        if isinstance(response, dict):
            return response
        # Old cache format: the top-level dict itself was {"fetched_at",
        # "selection"} with no wrapping "response" key.
        selection = data.get("selection")
        if isinstance(selection, list):
            return {"selection": selection}
        return None

    def load_cached(self) -> Optional[list[dict]]:
        """Tolerant read of the on-disk cache. Never raises -- returns None
        on any failure (missing file, malformed JSON, unexpected shape)."""
        response = self._load_cached_response()
        selection = response.get("selection") if isinstance(response, dict) else None
        if not isinstance(selection, list):
            return None
        return selection

    # -- combined -----------------------------------------------------
    def untick(self, slug: str) -> tuple[bool, str]:
        """Remove this editor's tick for `slug` on the dashboard (DELETE
        /api/v1/selection/<editor>/<slug>, companion token + identity auth).

        The tray's "Remove this project from this machine" calls this FIRST:
        while the tick stands, the server keeps the Syncthing folder shared
        and deleting the local copy just errors the folder. Returns
        (ok, message); never raises. On success the in-memory selection TTL
        is zeroed so the sequencer drops the project on its next poll."""
        if not self.enabled:
            return False, "dashboard_url is not configured"
        editor = str(self._editor_name_fn() or "").strip().lower()
        if not editor:
            return False, "no editor identity yet -- sign in first"
        url = (
            f"{self.dashboard_url.rstrip('/')}/api/v1/selection/"
            f"{quote(editor, safe='')}/{quote(str(slug), safe='')}"
        )
        headers = {}
        token = self.report_token()
        if token:
            headers["X-CCSync-Token"] = token
        if self._identity_token_fn is not None:
            try:
                identity_token = self._identity_token_fn()
            except Exception:
                identity_token = None
            if identity_token:
                headers["X-CCSync-Identity"] = identity_token
        req = urllib.request.Request(url, headers=headers, method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            return False, f"dashboard refused the untick (HTTP {exc.code})"
        except Exception as exc:
            return False, f"dashboard unreachable: {exc}"
        self._last_response_at = 0.0
        # ...and the failure throttle with it, so an untick that lands right
        # after a failed poll is still reflected on the very next get()
        # (COMP-CORE-3, 2026-08-14).
        self._last_failure_at = 0.0
        return True, "unticked"

    def get(self) -> tuple[Optional[list[dict]], str]:
        """Fetch live, falling back to the cache, falling back to nothing.

        Returns (selection_or_none, source) where source is one of "live",
        "cache", or "none".
        """
        live = self.fetch()
        if live is not None:
            return live, "live"
        cached = self.load_cached()
        if cached is not None:
            return cached, "cache"
        return None, "none"

    # -- project roots (sticky per-Resolve-project destination mapping) --
    def project_roots_result(self) -> tuple[dict[str, str], str]:
        """(mapping, source) where source is "live", "cache" or
        "unreachable".

        "No mapping exists" and "we could not ask" are completely different
        answers and this used to return {} for both. Callers then fell
        through to fixer.match_project_dir's token-overlap GUESS, so during a
        dashboard outage the same clip got a different destination than it
        had five minutes earlier -- gigabytes filed under a guessed root and
        lane-A-uploaded there (AUDIT_2 CORE-H9). Callers must refuse to
        resolve a destination on "unreachable".

        The cached response is also TTL'd. `_last_response` was set once by
        the base-rig one-shot fetch below and, because the sequencer never
        runs there, never refreshed -- so after an admin re-mapped a project
        root the base rig kept filing media under the old one until restart,
        with no indication.
        """
        response = self._last_response
        fresh = response is not None and (
            time.monotonic() - self._last_response_at
        ) < self.project_roots_ttl
        if not fresh and self.enabled:
            # Refresh (base rigs never do it in the background; on editors
            # the sequencer's own polling normally keeps this warm).
            stamp_before = self._last_response_at
            try:
                self.fetch()
            except Exception:
                pass
            if self._last_response is not None and self._last_response_at != stamp_before:
                return self._parse_project_roots(self._last_response), "live"
            if self._last_response is not None:
                # SYNC-14 (2026-08-11): a FAILED refresh leaves _last_response
                # untouched, and this arm returned that arbitrarily stale
                # mapping tagged "live" -- so with the dashboard down the base
                # rig filed media under a superseded root with full confidence,
                # which is the CORE-H9 outcome by another door. The mapping is
                # still the best answer available; the LABEL is what callers
                # act on. A successful fetch is the only thing that moves
                # _last_response_at, so it is the honest freshness test.
                return self._parse_project_roots(self._last_response), "cache"
            cached = self._load_cached_response()
            if cached is not None:
                return self._parse_project_roots(cached), "cache"
            return {}, "unreachable"
        if response is not None:
            return self._parse_project_roots(response), "live"
        cached = self._load_cached_response()
        if cached is not None:
            return self._parse_project_roots(cached), "cache"
        return {}, "unreachable" if self.enabled else "live"

    def get_project_roots(self) -> dict[str, str]:
        """Back-compat wrapper: the mapping only. Prefer
        project_roots_result() where "unreachable" matters."""
        mapping, _source = self.project_roots_result()
        return mapping

    @staticmethod
    def _parse_project_roots(response: Any) -> dict[str, str]:
        """Build {resolve project name (lower) -> "Projects/<rel>"}.

        UNSAFE ENTRIES ARE DROPPED. This mapping is the destination the popup
        fixer copies media into and the subpath app.consolidate_project hands
        to lane A -- but unlike every other consumer of a dashboard rel_path
        (sequencer._item_is_valid, repath._item_is_valid) it validated
        nothing at all, so a `../../..` rel_path from the dashboard became
        `Projects/../../..` and reached both a local copy destination and
        `rclone copy <that>` to the NAS. Same shared helper as everyone else
        (AUDIT_3 H-2)."""
        if not isinstance(response, dict):
            return {}
        roots = response.get("project_roots")
        if not isinstance(roots, list):
            return {}
        mapping: dict[str, str] = {}
        for entry in roots:
            if not isinstance(entry, dict):
                continue
            name = entry.get("resolve_project")
            rel_path = entry.get("rel_path")
            if not name or not rel_path:
                continue
            safe_rel = normalized_safe_rel(rel_path)
            if safe_rel is None:
                log.warning(
                    "selection: dropping project_roots entry for %r -- rel_path %r "
                    "is not a contained relative path", name, rel_path,
                )
                continue
            mapping[str(name).strip().lower()] = f"Projects/{safe_rel}"
        return mapping
