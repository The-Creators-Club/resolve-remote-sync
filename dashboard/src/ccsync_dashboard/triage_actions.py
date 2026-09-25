"""The server triage agent's action CATALOGUE and its executor.

2026-09-24, docs/SERVER_TRIAGE_AGENT.md section 4. The owner's decision: a
reply to the twice-daily server check can make the dashboard do "dashboard
actions only: a fixed catalogue of operations that already have a button;
never a shell". This module IS that catalogue. Anything not in `CATALOGUE`
cannot be done by reply, and adding an entry is a row here plus its test.

Three rules every entry keeps, and the reason each exists:

  * `execute` calls THE SAME FUNCTION the dashboard button's route calls (the
    route is cited beside each one). Never a new mutation path, never a raw
    SQL write: the button's function is the one that has been through every
    bug hunt, and it writes whatever audit row the button writes.
  * `validate` is run TWICE: when the model proposes the action (a proposal
    that names a machine that does not exist is dropped before it is offered)
    and again at the moment a reply chooses it (the breaker may have cleared
    in the twelve hours between). Reads only.
  * The executor never commits. The caller owns the transaction, so the
    action's write and its `triage_actions` state change land together.

`approve_device` from the plan's table is NOT here (v1 deviation, 2026-09-24):
its logic is inline in two routes that disagree (the JSON route audits, the
Users page partial does not), the Syncthing pending-device list it would
choose from is not in the evidence bundle, and it is the one entry that
GRANTS a new device access to footage. Extracting a shared helper would change
both routes' behaviour; that is a separate, owner-visible change.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from . import db

log = logging.getLogger("ccsync.dashboard.triage_actions")

# The in-process collector, registered by app.py's lifespan beside
# `app.state.collector`. The reply poller runs on its own daemon thread with no
# request and therefore no `app`, and `nudge_collector` needs the one object
# `api._nudge_collector` reaches through `request.app.state`.
_COLLECTOR: Any = None


def set_collector(collector: Any) -> None:
    global _COLLECTOR
    _COLLECTOR = collector


class ActionRefused(Exception):
    """Re-validation at execution time said no. The message is the reason, in
    words, for the confirmation email."""


# ------------------------------------------------------------------ params

MAX_NAME_CHARS = 128


def _str_param(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_NAME_CHARS:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    return value


def _int_param(value: Any) -> int | None:
    # bool is an int in Python; `true` from a model is not a job id.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) or None
    return None


_PARSERS = {"str": _str_param, "int": _int_param}


def normalise_params(spec: "Action", params: Any) -> tuple[dict[str, Any] | None, str]:
    """(clean params, "") or (None, reason). Required params present and well
    typed, nothing extra: a parameter the catalogue does not name is a
    proposal for something this entry does not do."""
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        return None, "its parameters are not a set of named values"
    extra = sorted(set(params) - {name for name, _t in spec.params})
    if extra:
        return None, f"it names parameter(s) this action does not take: {', '.join(extra)}"
    out: dict[str, Any] = {}
    for name, kind in spec.params:
        parsed = _PARSERS[kind](params.get(name))
        if parsed is None:
            return None, f"its {name!r} is missing or not a valid {kind}"
        out[name] = parsed
    # The routes' own normalisation (api.py:5231 api_push_machine_update,
    # ui.py:3951 partial_admin_machine_update): an editor is
    # case-folded, a hostname is kept as reported.
    if "editor" in out:
        out["editor"] = out["editor"].lower()
    return out, ""


# ------------------------------------------------------------- the readers
# Reads only. Everything a validator asks is a question the button's route
# already asks before it writes.

def _machine_row(conn: sqlite3.Connection, editor: str, machine: str):
    return conn.execute(
        "SELECT platform, update_requested_version FROM machines "
        "WHERE editor_username=? AND machine=?", (editor, machine)).fetchone()


def _need_machine(conn: sqlite3.Connection, p: Mapping[str, Any]) -> str | None:
    if _machine_row(conn, p["editor"], p["machine"]) is None:
        return f"there is no computer {p['machine']!r} for {p['editor']!r}"
    return None


def _current_package_for(conn: sqlite3.Connection, editor: str, machine: str):
    row = _machine_row(conn, editor, machine)
    platform = ((row["platform"] if row is not None else "") or "").strip().lower()
    return db.get_current_package(conn, platform, kind="companion")


# ------------------------------------------------------------ the entries

def _v_push_update(conn, settings, p) -> str | None:
    missing = _need_machine(conn, p)
    if missing:
        return missing
    current = _current_package_for(conn, p["editor"], p["machine"])
    if current is None:
        # api.py:5245's refusal (api_push_machine_update), in meaning.
        return "no current companion package is published for that computer's platform"
    row = conn.execute(
        "SELECT companion_version FROM machine_state "
        "WHERE editor_username=? AND machine=?", (p["editor"], p["machine"])).fetchone()
    running = str((row["companion_version"] if row is not None else "") or "")
    if running and running == str(current["version"]):
        return f"that computer already runs {running}, the current build"
    return None


def _x_push_update(conn, settings, p, actor) -> str:
    # Settings -> Packages [ UPDATE NOW ]: ui.py:3965
    # (partial_admin_machine_update) and api.py:5265 (api_push_machine_update)
    # both call db.request_machine_update with the platform's CURRENT build.
    current = _current_package_for(conn, p["editor"], p["machine"])
    if current is None:
        raise ActionRefused("no current companion package is published for "
                            "that computer's platform")
    if not db.request_machine_update(conn, p["editor"], p["machine"],
                                     current["version"], actor, db.utcnow_iso()):
        raise ActionRefused(f"there is no computer {p['machine']!r} for {p['editor']!r}")
    return (f"asked {p['editor']}/{p['machine']} to update to {current['version']} "
            f"on its next report")


def _v_cancel_push(conn, settings, p) -> str | None:
    row = _machine_row(conn, p["editor"], p["machine"])
    if row is None:
        return f"there is no computer {p['machine']!r} for {p['editor']!r}"
    if not row["update_requested_version"]:
        return "no update is waiting to be pushed to that computer"
    return None


def _x_cancel_push(conn, settings, p, actor) -> str:
    # Its [ CANCEL ]: ui.py:4120 (partial_admin_machine_update_cancel) and
    # api.py:5282 (api_cancel_machine_update) call exactly this, and write no
    # audit row; the triage_actions row is this path's record.
    db.clear_machine_update_request(conn, p["editor"], p["machine"])
    return f"withdrew the pushed update for {p['editor']}/{p['machine']}"


def _v_resume_breaker(conn, settings, p) -> str | None:
    # api.py:5327-5335 (api_resume_machine_lane_b): the machine must exist
    # AND its last report must show the breaker tripped (comp-lanes-ab-2: a
    # resume armed before a trip is a decision about a trip nobody has seen).
    if p["machine"] not in db.machines_of(conn, p["editor"]):
        return f"there is no computer {p['machine']!r} for {p['editor']!r}"
    if not db.machine_breaker_tripped(conn, p["editor"], p["machine"]):
        return ("that computer's last report does not show proxy download "
                "stopped, so there is nothing to resume")
    return None


def _x_resume_breaker(conn, settings, p, actor) -> str:
    # FLEET [ RESUME ] (CR-45): api.py:5338 (api_resume_machine_lane_b) and
    # ui.py:3992 (partial_admin_resume_lane_b) call db.request_lane_b_resume.
    if not db.request_lane_b_resume(conn, p["editor"], p["machine"], actor,
                                    db.utcnow_iso()):
        raise ActionRefused(f"there is no computer {p['machine']!r} for {p['editor']!r}")
    return (f"asked {p['editor']}/{p['machine']} to resume proxy download on "
            f"its next report")


def _v_halt_active(conn, settings, p) -> str | None:
    if not db.get_fleet_halt(conn)["active"]:
        return "syncing is not stopped fleet-wide"
    return None


def _x_clear_fleet_halt(conn, settings, p, actor) -> str:
    # The halt banner's release: ui.py:3306 (partial_admin_set_fleet_halt)
    # and api.py:5116 (api_set_fleet_halt) call db.set_fleet_halt with
    # active=False; it writes the audit row and the halt history itself.
    db.set_fleet_halt(conn, False, "", actor)
    return "released the fleet-wide stop; syncing starts again on each computer's next report"


def _x_keep_halted(conn, settings, p, actor) -> str:
    # [ KEEP HALTED ]: the same two routes with extend=True, which keeps the
    # original reason and start time and only moves the expiry.
    try:
        state = db.set_fleet_halt(conn, True, "", actor, extend=True)
    except ValueError as exc:
        raise ActionRefused(str(exc)) from None
    return f"kept syncing stopped until {state.get('expires_at') or 'the default expiry'}"


def _v_cancel_job(conn, settings, p) -> str | None:
    job = db.get_job(conn, p["job_id"])
    if job is None:
        return f"there is no job #{p['job_id']}"
    if job["state"] in db.JOB_TERMINAL_STATES:
        return f"job #{p['job_id']} is already {job['state']}"
    return None


def _x_cancel_job(conn, settings, p, actor) -> str:
    # POST /api/v1/jobs/{id}/cancel: api.py:10904 (api_cancel_job) and
    # ui.py:3448 (partial_admin_cancel_job) call db.request_job_cancel.
    state = db.request_job_cancel(conn, p["job_id"], actor)
    if state is None:
        raise ActionRefused(f"job #{p['job_id']} has already finished")
    if state == db.JOB_FAILED:
        return f"job #{p['job_id']} is over"
    # logic-admin-7 (2026-09-25): request_job_cancel answers "requested" for a
    # PINNED job too, and that one runs in this container's own Timeline
    # Cards worker (its should_stop), not on any computer: the owner's mail
    # must not send them to look for a machine. The request writes only the
    # cancel_requested_* columns, so re-reading the row gives its real state.
    job = db.get_job(conn, p["job_id"]) or {}
    if job.get("state") == db.JOB_PINNED:
        return (f"job #{p['job_id']} will stop when this server's own worker "
                f"next checks it; it is running here, not on any computer")
    return (f"job #{p['job_id']} will stop on its next report; the computer "
            f"running it is the only thing that can end it")


def _v_dismiss_notice(conn, settings, p) -> str | None:
    row = conn.execute("SELECT id FROM notices WHERE id=? AND cleared_at IS NULL",
                       (p["notice_id"],)).fetchone()
    if row is None:
        return f"there is no open notice #{p['notice_id']}"
    return None


def _x_dismiss_notice(conn, settings, p, actor) -> str:
    # PROBLEMS THE SERVER FOUND [ DISMISS ]: ui.py:1671 (partial_notice_dismiss)
    # calls db.dismiss_notice, which writes the notice.dismiss audit row.
    row = db.dismiss_notice(conn, p["notice_id"], actor)
    if row is None:
        raise ActionRefused(f"notice #{p['notice_id']} is already gone")
    return (f"dismissed notice #{p['notice_id']} ({row.get('kind')}); it comes back "
            f"by itself if the condition is still true")


def _v_request_diagnostics(conn, settings, p) -> str | None:
    return _need_machine(conn, p)


def _x_request_diagnostics(conn, settings, p, actor) -> str:
    # [ ASK THIS COMPUTER WHY ]: ui.py:4023 (partial_admin_ask_why) and
    # api.py:10194 (api_admin_ask_why) call db.request_diagnostics, which
    # writes the diagnostics.request audit row.
    if not db.request_diagnostics(conn, p["editor"], p["machine"], actor,
                                  db.utcnow_iso()):
        raise ActionRefused(f"there is no computer {p['machine']!r} for {p['editor']!r}")
    return (f"asked {p['editor']}/{p['machine']} for its diagnostics on its next "
            f"report")


def _v_nudge(conn, settings, p) -> str | None:
    if _COLLECTOR is None:
        return "this server's background jobs are not running in this process"
    return None


def _x_nudge(conn, settings, p, actor) -> str:
    # The tick's nudge: api.py:2420 (_nudge_collector) calls collector.nudge()
    # on app.state.collector, the object registered here by app.py.
    collector = _COLLECTOR
    if collector is None:
        raise ActionRefused("this server's background jobs are not running in this process")
    collector.nudge()
    log.info("triage: %s nudged the collector", actor)
    return "asked the background jobs to reconcile sharing now"


@dataclass(frozen=True)
class Action:
    name: str
    params: tuple[tuple[str, str], ...]
    # One line for the email, formatted with the params.
    summary: str
    # For the prompt: when this is the right thing to suggest.
    when: str
    validate: Callable[[sqlite3.Connection, Any, Mapping[str, Any]], str | None]
    execute: Callable[[sqlite3.Connection, Any, Mapping[str, Any], str], str]


_EM = (("editor", "str"), ("machine", "str"))

CATALOGUE: dict[str, Action] = {a.name: a for a in (
    Action("push_update", _EM,
           "Push the current companion build to {editor}/{machine}",
           "a computer is behind the current build and nothing in the evidence "
           "says the build is bad or the machine is busy",
           _v_push_update, _x_push_update),
    Action("cancel_push", _EM,
           "Withdraw the pushed update for {editor}/{machine}",
           "a pushed update is waiting on a computer and the evidence says it "
           "cannot or should not be delivered (withheld, retracted, wrong platform)",
           _v_cancel_push, _x_cancel_push),
    Action("resume_breaker", _EM,
           "Resume proxy download on {editor}/{machine}",
           "a computer's proxy download stopped itself (the lane B breaker) and "
           "the evidence says the server tree is intact, so the trip is stale",
           _v_resume_breaker, _x_resume_breaker),
    Action("clear_fleet_halt", (),
           "Start syncing again everywhere (release the fleet-wide stop)",
           "a fleet-wide stop is active and the evidence says its reason no "
           "longer holds. Never suggest it without saying why the reason is gone",
           _v_halt_active, _x_clear_fleet_halt),
    Action("keep_halted", (),
           "Keep syncing stopped everywhere, for 24 hours from the reply",
           "a fleet-wide stop is active, is about to expire, and its reason "
           "still holds",
           _v_halt_active, _x_keep_halted),
    Action("cancel_job", (("job_id", "int"),),
           "Cancel fleet job #{job_id}",
           "a fleet job is stuck, starved or failing repeatedly and running it "
           "again cannot help",
           _v_cancel_job, _x_cancel_job),
    Action("dismiss_notice", (("notice_id", "int"),),
           "Dismiss notice #{notice_id}",
           "an open notice is about a condition the evidence shows is over (it "
           "comes back by itself if it is still true)",
           _v_dismiss_notice, _x_dismiss_notice),
    Action("request_diagnostics", _EM,
           "Ask {editor}/{machine} for its diagnostics",
           "a computer is not syncing and the evidence does not say why; its "
           "diagnostics bundle is the next thing a person would read",
           _v_request_diagnostics, _x_request_diagnostics),
    Action("nudge_collector", (),
           "Ask the server's background jobs to run now",
           "shares or plans look out of step and the collector is healthy; this "
           "only makes the next reconcile happen sooner",
           _v_nudge, _x_nudge),
)}


def describe(name: str, params: Mapping[str, Any]) -> str:
    """The one line the email and the confirmation print for an action."""
    spec = CATALOGUE.get(name)
    if spec is None:
        return str(name)
    try:
        return spec.summary.format(**params)
    except (KeyError, IndexError, ValueError):
        return spec.summary


def catalogue_for_prompt() -> str:
    """The catalogue as the model reads it: name, parameters, what it does,
    when it is right. Rendered from `CATALOGUE` so the prompt can never offer
    something the executor does not have."""
    lines = []
    for spec in CATALOGUE.values():
        args = ", ".join(f"{n}: {t}" for n, t in spec.params) or "no parameters"
        lines.append(f"- {spec.name}({args}): {spec.summary.format(**{n: '<' + n + '>' for n, _t in spec.params})}. "
                     f"Right when: {spec.when}.")
    return "\n".join(lines)


def validate(conn: sqlite3.Connection, settings: Any, name: Any,
             params: Any) -> tuple[dict[str, Any] | None, str]:
    """(clean params, "") when the action may be offered or run NOW, else
    (None, the reason in words). Never raises: a reader that fails is a
    refusal, because an action whose target could not be checked must not be
    offered as though it had been."""
    spec = CATALOGUE.get(str(name or ""))
    if spec is None:
        return None, f"{name!r} is not an action a reply can carry out"
    clean, why = normalise_params(spec, params)
    if clean is None:
        return None, why
    try:
        refusal = spec.validate(conn, settings, clean)
    except Exception as exc:                                        # noqa: BLE001
        log.exception("triage: validating %s failed", spec.name)
        return None, f"it could not be checked ({type(exc).__name__})"
    if refusal:
        return None, refusal
    return clean, ""


def execute(conn: sqlite3.Connection, settings: Any, name: str,
            params: Mapping[str, Any], actor: str) -> str:
    """Run one catalogue action through its button's function. Raises
    ActionRefused for a re-validation that says no; anything else it raises is
    a failure the caller records. Does NOT commit."""
    clean, why = validate(conn, settings, name, params)
    if clean is None:
        raise ActionRefused(why)
    return CATALOGUE[name].execute(conn, settings, clean, actor)


def params_json(params: Mapping[str, Any]) -> str:
    return json.dumps(dict(params), sort_keys=True)
