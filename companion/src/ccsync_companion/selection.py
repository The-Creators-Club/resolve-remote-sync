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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

log = logging.getLogger("ccsync.selection")

HttpGetFn = Callable[[str, dict, float], Any]

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
    ) -> None:
        self.cfg = cfg
        self.state_dir = state_dir
        self._http_get = http_get or default_http_get
        self.timeout = timeout

        self.dashboard_url = str(cfg.get("dashboard_url", "")).strip()
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

    @property
    def enabled(self) -> bool:
        return bool(self.dashboard_url)

    # -- fetch -----------------------------------------------------
    def fetch(self) -> Optional[list[dict]]:
        """Single synchronous fetch. Never raises -- returns None on any
        failure (network error, bad JSON, unexpected shape)."""
        if not self.enabled:
            return None
        editor_name = str(self._editor_name_fn() or "").strip().lower()
        if not editor_name:
            # No verified/configured identity yet (e.g. require_login=true
            # and not signed in). Requesting /api/v1/selection/ with no
            # username 404s every single poll forever -- skip the request
            # entirely and let get() fall back to the cache/none, same as
            # any other fetch failure, but without the network round trip
            # or log spam (see the selection-identity finding).
            return None
        url = f"{self.dashboard_url.rstrip('/')}/api/v1/selection/{quote(editor_name, safe='')}"
        headers = {}
        if self.dashboard_token:
            headers["X-CCSync-Token"] = self.dashboard_token
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
            return None

        self._error_logged = False
        self._last_response = response if isinstance(response, dict) else {"selection": selection}
        self._write_cache(self._last_response)
        return selection

    def _write_cache(self, response: dict[str, Any]) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "response": response,
            }
            self._cache_path.write_text(json.dumps(payload), encoding="utf-8")
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
    def get_project_roots(self) -> dict[str, str]:
        """Case-insensitive mapping of Resolve project name -> tree
        destination prefix ("Projects/<year>/<series>/<project>"), built
        from the server's "project_roots" list (see popup.py's server_roots
        lookup). Prefers the most recently fetched live response this run,
        falling back to the on-disk cache; returns {} when neither is
        available or the field is absent (older server / never fetched).
        Never raises."""
        response = self._last_response
        if response is None:
            response = self._load_cached_response()
        if response is None and self.enabled:
            # Base rig: the sequencer never runs, so nothing populates the
            # cache in the background. A one-shot fetch here keeps popup
            # destinations honoring admin-set project roots. fetch() stores
            # the response and never raises.
            try:
                self.fetch()
            except Exception:
                pass
            response = self._last_response
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
            mapping[str(name).strip().lower()] = f"Projects/{rel_path}"
        return mapping
