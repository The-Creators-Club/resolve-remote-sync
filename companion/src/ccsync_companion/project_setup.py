"""New-Resolve-project onboarding prompt.

The dashboard's report response carries a conditional
`resolve_project_unmapped: "<name>"` key when the currently-open Resolve
project has no server-side root mapping and the server's auto-match found
nothing (see the dashboard's api_report). This module consumes that signal:

  - the FIRST time a given project is flagged (ever -- persisted across
    restarts in state/project_prompts.json), show a confirm dialog offering
    to set it up; accepting opens the dashboard's /project-setup deep link.
  - declining (or closing the dialog, or having no display) permanently
    silences the auto-prompt for that project; the tray's conditional
    "Set up '<X>' on the server…" item remains as the manual re-trigger
    for whichever project is currently flagged.

Never-raise ethos, injectable collaborators for tests -- same conventions
as upgrade.py. Thread model: note_report_response() arrives on the reporter
thread, note_project_changed() on the watcher thread, trigger_setup() from
tray daemon threads; shared state goes through _lock. The confirm dialog
runs on its own daemon thread guarded by the app-wide popup lock (Tk is not
thread-safe -- see app.py's _popup_active_lock).
"""
from __future__ import annotations

import json
import logging
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from . import popup

log = logging.getLogger("ccsync.project_setup")

STATE_FILENAME = "project_prompts.json"


class ProjectSetupPrompter:
    def __init__(
        self,
        cfg: dict[str, Any],
        state_dir: Path,
        popup_lock: threading.Lock,
        confirm: Callable[..., bool] = popup.confirm_dialog,
        open_url: Callable[[str], Any] = webbrowser.open,
        notify: Optional[Callable[[str, str], None]] = None,
        get_current_project: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self.cfg = cfg
        self.state_path = Path(state_dir) / STATE_FILENAME
        self._popup_lock = popup_lock
        self._confirm = confirm
        self._open_url = open_url
        self._notify = notify
        self._get_current_project = get_current_project
        self._lock = threading.Lock()
        self._unmapped: Optional[str] = None
        self._prompt_in_flight = False
        self._asked: dict[str, str] = self._load_asked()

    # -- persisted "already asked" map ---------------------------------
    def _load_asked(self) -> dict[str, str]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            asked = data.get("asked")
            if isinstance(asked, dict):
                return {str(k): str(v) for k, v in asked.items()}
        except (OSError, ValueError):
            pass
        return {}

    def _record_asked(self, name: str) -> None:
        self._asked[name.strip().lower()] = datetime.now(timezone.utc).isoformat()
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps({"asked": self._asked}, indent=1), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("could not persist project-prompt state: %s", exc)

    def _was_asked(self, name: str) -> bool:
        return name.strip().lower() in self._asked

    # -- signals --------------------------------------------------------
    @property
    def unmapped_project(self) -> Optional[str]:
        """The currently-flagged unmapped project name (tray item source)."""
        with self._lock:
            return self._unmapped

    def note_report_response(self, resp: Any) -> None:
        """Feed a parsed report response. Never raises."""
        try:
            name = None
            if isinstance(resp, dict):
                raw = resp.get("resolve_project_unmapped")
                if isinstance(raw, str) and raw.strip():
                    name = raw.strip()
            with self._lock:
                if name is None:
                    if isinstance(resp, dict):
                        self._unmapped = None
                    return
                self._unmapped = name
                if self._was_asked(name) or self._prompt_in_flight:
                    return
                self._prompt_in_flight = True
            threading.Thread(
                target=self._prompt_worker, args=(name,), daemon=True,
                name="ccsync-project-setup-prompt",
            ).start()
        except Exception:
            log.exception("note_report_response failed")

    def note_project_changed(self, name: str) -> None:
        """Watcher says a different project is now open -- a stale unmapped
        flag for the previous project must not keep offering setup for it.
        The next report re-flags the new project if it's also unmapped."""
        try:
            with self._lock:
                if self._unmapped is not None and self._unmapped != name:
                    self._unmapped = None
        except Exception:
            log.exception("note_project_changed failed")

    # -- the prompt ------------------------------------------------------
    def setup_url(self, name: str) -> str:
        base = str(self.cfg.get("dashboard_url", "")).strip().rstrip("/")
        # safe="" so "/" in a project name is escaped too -- it's a query
        # param value, not a path segment.
        return f"{base}/project-setup?resolve_project={quote(name, safe='')}"

    def _prompt_worker(self, name: str) -> None:
        try:
            if not self._popup_lock.acquire(blocking=False):
                # Another dialog is up; skip -- the next report retries
                # (we haven't recorded "asked" yet).
                return
            try:
                # The editor may have switched projects while the report was
                # in flight -- never prompt about a project no longer open.
                if self._get_current_project is not None:
                    current = None
                    try:
                        current = self._get_current_project()
                    except Exception:
                        pass
                    if current is not None and current.strip() != name.strip():
                        return
                # Record BEFORE showing: decline, closing the window, and
                # the no-display False fallback all count as "asked" -- the
                # tray item is the escape hatch, never a repeat auto-prompt.
                self._record_asked(name)
                accepted = self._confirm(
                    "NEW PROJECT",
                    f"Project '{name}' isn't set up on the server —\n"
                    "no media will sync for it until it has a home.\n\n"
                    "Set it up now? (Opens the dashboard in your browser.)",
                    ok_label="SET UP NOW",
                )
            finally:
                self._popup_lock.release()
            if accepted:
                self._open_url(self.setup_url(name))
            elif self._notify is not None:
                try:
                    self._notify(
                        f"You can set up '{name}' later from the tray menu.",
                        "ccsync-companion",
                    )
                except Exception:
                    pass
        except Exception:
            log.exception("project-setup prompt failed")
        finally:
            with self._lock:
                self._prompt_in_flight = False

    def trigger_setup(self, name: Optional[str] = None) -> None:
        """Tray-facing manual trigger: open the deep link directly -- the
        menu click IS the consent, no extra dialog."""
        try:
            if name is None:
                name = self.unmapped_project
            if not name:
                return
            self._open_url(self.setup_url(name))
        except Exception:
            log.exception("trigger_setup failed")
