"""The admin-side Resolve undo, the companion half (SYS-15b, 2026-08-29).

An admin pressed [ UNDO THIS CHANGE ] on the dashboard for a change CC Sync
made on THIS machine. Until now that button only existed in this machine's own
tray (docs/RESOLVE_EDIT_SAFETY.md), so a relink pass that went wrong on
somebody else's computer could not be put back until that person was next at
their keyboard -- while the lane B breaker, whose blast radius is smaller, got
[ RESUME ] on the command channel in CR-45.

THE REPLAY IS NOT REIMPLEMENTED HERE. This module resolves a journal id to a
file and hands it to `resolve_bridge.undo_last_relink(session_path=...)`, the
same function the tray menu item calls, so both routes carry the same refusals
(the wrong project is open, the clip has left the media pool) and there is one
place where a media-pool write can happen.

RETRYING, NOT FAILING. An undo asked for while Resolve is closed, or while
another project is open, is answered `retrying`: the dashboard records the
attempt WITHOUT retiring the command, and it is offered again on the next
report. That is the file_moves contract (RES-1), and it is right for the same
reason -- the condition clears itself when the editor opens the project, and
retiring the command would leave the wrong paths in place with an admin
believing they had been put back.

The ledger is on disk beside the file-move ledger: a command redelivered after
a restart is answered from what happened the first time rather than replayed.
A replay is close to idempotent anyway (the second pass finds no clip at the
`new` path and undoes nothing), but "close to" is not a thing to rely on when
the operation is a media-pool write.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ccsync.resolve_undo")

LEDGER_FILENAME = "resolve_undos.json"
LEDGER_MAX_ENTRIES = 100
# How long an unanswerable undo keeps saying "retrying" before it becomes a
# failure. A week: an editor away on a shoot is the case this covers, and a
# command that retries for ever is a command nobody ever sees the end of.
RETRY_MAX_SECONDS = 7 * 24 * 3600

# -- what "not yet" looks like in the bridge's own words (RES-4, 2026-09-04) --
#
# Classifying a refusal by PROSE was always going to break, and it broke on
# the commonest state of all: Resolve open at the Project Manager answers
# "no project open in Resolve", which matched none of the old substrings (no
# "not", and "project open" is not "is open"), so an undo an admin asked for
# was recorded FAILED and never offered again -- although the editor opening
# their project is exactly what clears it. `_SCRIPTING_ERROR_MESSAGE`
# ("Resolve didn't answer...") failed the same way: "didn't" contains no
# "not".
#
# PARKED is the answer for the subset that is waiting for a HUMAN ACTION we
# can name: open a project. It is still retried, and the wording tells the
# admin what will resume it rather than implying CC Sync is stuck.
PARK_HINTS = (
    "no project open",
    "no timeline open",
    "make sure a project is open",
    "open that project",
)
# Retried, but nobody can be told what to do about it: Resolve went away
# mid-call, the media pool would not answer.
RETRY_HINTS = (
    "is open",
    "didn't answer",
    "did not answer",
)
PARKED_DETAIL = (
    "Parked: there is no project open in Resolve on this computer. CCSync "
    "will put the clip paths back on its own the next time that project is "
    "open."
)
# The state the WIRE carries for a parked undo. The dashboard's
# ResolveUndoResultIn accepts done/failed/retrying only (api.py, v40), and an
# unknown value fails validation for the WHOLE report -- so a deployed
# dashboard would stop hearing about a machine's sync entirely. "retrying" is
# also true: parked IS retrying, with a reason. `apply_undo(allow_parked=True)`
# returns the finer word once a dashboard that accepts it is deployed.
STATE_PARKED = "parked"
STATE_RETRYING = "retrying"


def parse_command(raw: Any) -> Optional[dict[str, Any]]:
    """One `commands.resolve_undo` entry, validated, or None.

    The journal id is NOT resolved here -- `resolve_journal.session_by_id`
    does that, and it is the only thing that turns this string into a path.
    """
    if not isinstance(raw, dict):
        return None
    try:
        request_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    journal = str(raw.get("journal") or "").strip()
    if request_id <= 0 or not journal:
        return None
    return {
        "id": request_id,
        "journal": journal,
        "project": str(raw.get("project") or ""),
        "requested_by": str(raw.get("requested_by") or "your administrator"),
        "requested_at": str(raw.get("requested_at") or ""),
    }


class UndoLedger:
    """What this machine has already answered. Best effort throughout: a
    ledger that cannot be written must not stop an undo an admin asked for."""

    def __init__(self, state_dir: Path) -> None:
        self.path = Path(state_dir) / LEDGER_FILENAME
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._entries = {str(k): v for k, v in raw.items()
                                 if isinstance(v, dict)}
        except FileNotFoundError:
            self._entries = {}
        except Exception:
            log.warning("resolve undo: the ledger at %s could not be read; starting "
                        "empty (an undo may be re-applied once)", self.path)
            self._entries = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if len(self._entries) > LEDGER_MAX_ENTRIES:
                keep = sorted(self._entries.items(),
                              key=lambda kv: float(kv[1].get("at") or 0))
                self._entries = dict(keep[-LEDGER_MAX_ENTRIES:])
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._entries), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            log.exception("resolve undo: could not write the ledger")

    def entry(self, request_id: int) -> Optional[dict[str, Any]]:
        return self._entries.get(str(int(request_id)))

    def record(self, request_id: int, ok: bool, detail: str,
               state: str, attempts: int = 1) -> dict[str, Any]:
        key = str(int(request_id))
        previous = self._entries.get(key) or {}
        parked = state == STATE_PARKED
        # A parked undo is an OPEN one: it is stored as "retrying" because
        # that is the word every reader of this ledger tests for when it
        # decides whether to ask this machine again (app._apply_resolve_undo),
        # and a state nobody recognises would retire the command -- the exact
        # bug RES-4 is about, moved one file along. `parked` keeps the finer
        # fact for anything that wants to say WHY.
        stored = STATE_RETRYING if parked else state
        entry = {
            "ok": bool(ok), "detail": str(detail or "")[:512], "state": stored,
            "parked": parked,
            "attempts": int(previous.get("attempts") or 0) + 1
                        if stored == STATE_RETRYING else int(attempts),
            "first_at": float(previous.get("first_at") or time.time()),
            "at": time.time(),
        }
        self._entries[key] = entry
        self._save()
        return entry

    def gave_up(self, entry: dict[str, Any]) -> bool:
        """A retry that has been retrying for a week is an answer now."""
        try:
            return (time.time() - float(entry.get("first_at") or 0)) > RETRY_MAX_SECONDS
        except (TypeError, ValueError):
            return False


def apply_undo(command: dict[str, Any], undo_fn=None,
               resolver=None, allow_parked: bool = False) -> tuple[bool, str, str]:
    """Replay one journal in reverse. Returns (ok, detail, state).

    `state` is "done", "failed" or "retrying" -- the same three the dashboard
    records for a file move, with "retrying" meaning "ask me again": Resolve
    is not running, or the project the change was made in is not the one that
    is open. Never raises: this runs on the reporter thread.

    `allow_parked` (RES-4) returns "parked" instead of "retrying" for the
    subset that is waiting for a named human action -- no project open in
    Resolve. OFF by default because the value goes on the wire and the
    deployed dashboard validates it against a three-word Literal; see
    STATE_PARKED. The DETAIL says parked either way, which is the half an
    admin reads.
    """
    if resolver is None:
        from . import resolve_journal

        resolver = resolve_journal.session_by_id
    path = resolver(command["journal"])
    if path is None:
        # NOT a retry: a journal this machine does not have is not going to
        # appear. It has been swept (60 days), or the machine was rebuilt.
        return (False,
                f"this computer no longer has the record {command['journal']}: it has "
                "been cleared, or this is not the computer the change was made on",
                "failed")
    if undo_fn is None:
        from . import resolve_bridge

        undo_fn = resolve_bridge.undo_last_relink
    try:
        result = undo_fn(session_path=path)
    except Exception as exc:                                          # noqa: BLE001
        log.exception("resolve undo: the replay raised")
        return False, f"the undo could not run on this computer ({exc})", "retrying"
    message = str((result or {}).get("message") or "")
    if (result or {}).get("ok"):
        return True, message or "put the clip paths back", "done"
    # The refusals that clear themselves, in the bridge's own words: Resolve
    # closed, another project open, the media pool unreadable. Answering
    # `failed` here is what would let an admin believe a change had been put
    # back when it had not.
    lowered = message.lower()
    if any(hint in lowered for hint in PARK_HINTS):
        return False, PARKED_DETAIL, (STATE_PARKED if allow_parked else STATE_RETRYING)
    if (not message
            or any(hint in lowered for hint in RETRY_HINTS)
            or "resolve" in lowered and "not" in lowered):
        return False, message or "Resolve did not answer on this computer", STATE_RETRYING
    return False, message, "failed"
