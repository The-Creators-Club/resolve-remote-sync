"""The fleet job scheduler: capability match -> policy -> rank -> offer.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §4.4, phase 0 (2026-08-29). The queue
itself is `db.py` (the table, the lease, the compare-and-set claim); this
module is the only thing in the dashboard with an OPINION about which machine
should do what, and it is deliberately dumb:

  1. capability match  -- hard requirements only (db.job_requirements_met).
     A machine that cannot run a job never sees it.
  2. policy            -- not halted, not mid-upgrade, lane B breaker not
     tripped, not already holding a job, and idle enough for this kind. The
     base rig is exempt from the idle floor: nobody sits at it.
  3. rank              -- priority, then age. Phase 4 adds "prefer nvenc",
     "prefer the machine next to the media", "least loaded".
  4. OFFER, DO NOT PUSH -- the ids ride the report reply and the companion
     claims one on a fleet route. Two machines offered the same job cannot
     both get it: the claim is a compare-and-set (db.claim_job).

THE FAILURE MODE OF A SCHEDULER IS INVISIBLE (§6 phase 4's risk): a scheduler
that quietly assigns nothing looks exactly like a fleet with nothing to do.
So `explain()` exists from the FIRST commit, is served at
`GET /api/v1/jobs/<id>/why`, and answers per machine in the words an admin
can act on -- the way [ VRAM ] is shown even when nothing is running.

`idle_seconds` keeps idle.py's contract end to end: **None means cannot tell
means NOT IDLE**. A machine with no idle answer is busy, here and in the
companion's own gate. That is the difference between harnessing idle compute
and transcoding under the editor's hands.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Mapping

from . import db

log = logging.getLogger("ccsync.dashboard.jobs")

# Seconds of no keyboard or mouse before a machine may be given work of this
# kind. proxy_gen's own default is 300 s and this matches it deliberately: an
# editor should not have to learn two different meanings of "away".
JOB_IDLE_FLOOR_SECONDS: dict[str, int] = {db.JOB_KIND_WHISPER: 300}
JOB_IDLE_FLOOR_DEFAULT = 300

# Reasons, as constants, because the fleet page and the tests both name them.
REFUSE_KIND_UNKNOWN = "kind_unknown"
REFUSE_CAPABILITY = "capability"
REFUSE_FLEET_HALT = "fleet_halt"
REFUSE_MACHINE_HALT = "machine_halt"
REFUSE_UPGRADING = "upgrading"
REFUSE_BREAKER = "lane_b_breaker"
REFUSE_BUSY_WITH_JOB = "already_holds_a_job"
REFUSE_NOT_IDLE = "not_idle"
REFUSE_NO_CAPABILITIES = "no_capabilities_reported"


def idle_floor(kind: str) -> int:
    return int(JOB_IDLE_FLOOR_SECONDS.get(str(kind or ""), JOB_IDLE_FLOOR_DEFAULT))


def machine_facts(
    conn: sqlite3.Connection, editor: str, machine: str,
    capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything policy() needs about one computer, in one place.

    `capabilities` overrides the stored ones -- the report handler passes the
    section that just arrived, which is fresher than the row it is about to
    write, and the claim route passes what the claimant asserts NOW."""
    caps = dict(capabilities) if capabilities is not None else \
        db.machine_capabilities(conn, editor, machine)
    row = conn.execute(
        "SELECT mode, halt_active, breaker_tripped FROM machine_state "
        " WHERE editor_username=? AND machine=?", (editor, machine)).fetchone()
    upgrade = db.machine_update_request(conn, editor, machine)
    return {
        "editor": editor,
        "machine": machine,
        "capabilities": caps,
        "mode": (row["mode"] if row is not None else None) or "editor",
        "halt_active": bool(row["halt_active"]) if row is not None else False,
        "breaker_tripped": bool(row["breaker_tripped"]) if row is not None else False,
        "upgrading": bool(upgrade),
        "live_jobs": db.machine_live_jobs(conn, editor, machine),
        "fleet_halt": bool(db.get_fleet_halt(conn)["active"]),
    }


def policy_refusal(facts: Mapping[str, Any], kind: str) -> tuple[str, str]:
    """Why this machine may take no job of this kind right now, or ("", "").

    Order matters: the first true answer is the one shown, and it is the
    order an admin would ask the questions in -- is everything stopped, is
    this machine stopped, is it in the middle of something, is anyone sitting
    at it.
    """
    if facts.get("fleet_halt"):
        return REFUSE_FLEET_HALT, "the whole fleet is halted"
    if facts.get("halt_active"):
        return REFUSE_MACHINE_HALT, "this machine's sync is halted"
    if facts.get("upgrading"):
        return REFUSE_UPGRADING, "this machine has an update waiting to apply"
    if facts.get("breaker_tripped"):
        return (REFUSE_BREAKER,
                "this machine's proxy-download breaker is tripped, so it is "
                "not in a state anyone should add work to")
    if facts.get("live_jobs"):
        held = facts["live_jobs"][0]
        return (REFUSE_BUSY_WITH_JOB,
                f"this machine is already holding job #{held['id']} ({held['kind']})")
    caps = dict(facts.get("capabilities") or {})
    if not caps:
        return (REFUSE_NO_CAPABILITIES,
                "this machine has not reported what it can do (a companion "
                "older than the job runner)")
    # THE BASE RIG IS EXEMPT (MULTI_MACHINE_PLAN.md WP0): nobody sits at it,
    # and idle.py on a machine with no console session cannot answer anyway.
    if str(facts.get("mode") or "editor") != "base":
        floor = idle_floor(kind)
        idle = caps.get("idle_seconds")
        # None means cannot tell means NOT IDLE (idle.py's contract).
        if idle is None:
            return (REFUSE_NOT_IDLE,
                    "this machine cannot say how long it has been idle, which "
                    "counts as somebody being at it")
        try:
            if float(idle) < floor:
                return (REFUSE_NOT_IDLE,
                        f"somebody is at this machine (idle {int(float(idle))}s, "
                        f"{kind} needs {floor}s)")
        except (TypeError, ValueError):
            return (REFUSE_NOT_IDLE, "this machine's idle answer is unreadable")
    return "", ""


def offers_for_machine(
    conn: sqlite3.Connection, editor: str, machine: str,
    capabilities: Mapping[str, Any] | None = None,
    now: str | None = None, limit: int = 8,
) -> dict[str, Any]:
    """What this machine may claim right now.

    -> {"offered": [job ids]}, plus "refused" (id -> reason) for the log and
    the why page. The list is SMALL on purpose: it rides every report of every
    machine in the fleet, and a companion claims one job at a time anyway.

    The same job is offered to every machine that could do it. That is the
    design ("offer, don't push"): the compare-and-set decides, and a fleet
    where one machine's reply was lost still gets the work done.
    """
    facts = machine_facts(conn, editor, machine, capabilities)
    offered: list[int] = []
    refused: dict[int, str] = {}
    for job in db.queued_jobs(conn):
        kind = str(job["kind"])
        if kind not in db.JOB_KINDS:
            refused[int(job["id"])] = REFUSE_KIND_UNKNOWN
            continue
        ok, _why = db.job_requirements_met(job.get("requires"), facts["capabilities"])
        if not ok:
            refused[int(job["id"])] = REFUSE_CAPABILITY
            continue
        reason, _sentence = policy_refusal(facts, kind)
        if reason:
            refused[int(job["id"])] = reason
            continue
        offered.append(int(job["id"]))
        if len(offered) >= max(1, int(limit)):
            break
    return {"offered": offered, "refused": refused}


def explain(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    """"Unschedulable, and why", per machine. None if there is no such job.

    Every machine the dashboard has ever heard from gets a line, including the
    ones that would take it: "nothing can run this" and "three machines could
    but all three have someone sitting at them" are different problems with
    the same symptom (an empty fleet grid), and this is the page that tells
    them apart.
    """
    job = db.get_job(conn, int(job_id))
    if job is None:
        return None
    kind = str(job["kind"])
    lines: list[dict[str, Any]] = []
    if job["state"] in db.JOB_TERMINAL_STATES or job["state"] in db.JOB_HELD_STATES:
        # Not a scheduling question any more. Say so rather than listing
        # eight machines that "could have".
        return {
            "job": job, "schedulable": False, "machines": [],
            "summary": _terminal_summary(job),
        }
    for row in conn.execute(
        "SELECT editor_username, machine FROM machine_state "
        " ORDER BY editor_username, machine"
    ).fetchall():
        editor, machine = row["editor_username"], row["machine"]
        facts = machine_facts(conn, editor, machine)
        ok, why = db.job_requirements_met(job.get("requires"), facts["capabilities"])
        if not ok:
            lines.append({"editor": editor, "machine": machine, "ok": False,
                          "reason": REFUSE_CAPABILITY, "why": why})
            continue
        reason, sentence = policy_refusal(facts, kind)
        if reason:
            lines.append({"editor": editor, "machine": machine, "ok": False,
                          "reason": reason, "why": sentence})
            continue
        lines.append({"editor": editor, "machine": machine, "ok": True,
                      "reason": "", "why": "this machine can take it"})
    can = [m for m in lines if m["ok"]]
    if kind not in db.JOB_KINDS:
        summary = (f"this dashboard does not know the job kind {kind!r}, so no "
                   f"machine will ever be offered it")
    elif can:
        summary = (f"{len(can)} machine(s) can take this job; it is waiting to "
                   f"be claimed on their next report")
    elif not lines:
        summary = "no machine has ever reported to this dashboard"
    else:
        summary = _blocked_summary(lines)
    return {"job": job, "schedulable": bool(can) and kind in db.JOB_KINDS,
            "machines": lines, "summary": summary}


def _terminal_summary(job: Mapping[str, Any]) -> str:
    state = str(job["state"])
    if state in db.JOB_HELD_STATES:
        return (f"{job['claimed_by']}/{job['claimed_machine']} is holding this "
                f"job (lease until {job['lease_expires_at']})")
    if state == db.JOB_DONE:
        return "this job is done"
    if state == db.JOB_ABANDONED:
        return (f"given up after {job['attempts']} attempt(s): "
                f"{job['last_error'] or 'no error recorded'}")
    return f"this job failed and will not be retried: {job['last_error']}"


def _blocked_summary(lines: list[dict[str, Any]]) -> str:
    """One sentence naming the COMMONEST reason, because that is the one
    thing an admin can act on ("everyone is at their desk" is a different
    action from "nobody has a GPU")."""
    counts: dict[str, int] = {}
    for line in lines:
        counts[line["reason"]] = counts.get(line["reason"], 0) + 1
    reason, count = max(counts.items(), key=lambda kv: kv[1])
    words = {
        REFUSE_CAPABILITY: "cannot do this kind of work",
        REFUSE_FLEET_HALT: "are under a fleet halt",
        REFUSE_MACHINE_HALT: "have sync halted",
        REFUSE_UPGRADING: "have an update waiting",
        REFUSE_BREAKER: "have a tripped proxy-download breaker",
        REFUSE_BUSY_WITH_JOB: "are already holding a job",
        REFUSE_NOT_IDLE: "have somebody sitting at them",
        REFUSE_NO_CAPABILITIES: "have not said what they can do",
        REFUSE_KIND_UNKNOWN: "would never be offered this kind",
    }.get(reason, reason)
    return (f"no machine can take this job right now: {count} of {len(lines)} "
            f"{words}")
