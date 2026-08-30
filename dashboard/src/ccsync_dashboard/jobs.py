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

import datetime as dt
import logging
import sqlite3
from typing import Any, Mapping

from . import db

log = logging.getLogger("ccsync.dashboard.jobs")

# Seconds of no keyboard or mouse before a machine may be given work of this
# kind. proxy_gen's own default is 300 s and this matches it deliberately: an
# editor should not have to learn two different meanings of "away".
#
# THE FLOOR IS PER KIND BECAUSE THE COST IS (phase 1, 2026-08-30). A whisper
# pass is minutes of GPU work; an audio extraction is `-c:a copy` on one file
# and a peaks pass is an 8 kHz decode, both of them seconds and both of them
# I/O bound. Making somebody's laptop wait five minutes of stillness before it
# will copy an audio track is how a lane sits on a spinner while a fleet of
# capable machines does nothing -- so the cheap kinds get 60 s, which is still
# long enough that it is not happening under an editor's hands mid-sentence.
JOB_IDLE_FLOOR_SECONDS: dict[str, int] = {
    db.JOB_KIND_WHISPER: 300,
    db.JOB_KIND_PROXY_480P: 300,
    db.JOB_KIND_AUDIO_EXTRACT: 60,
    db.JOB_KIND_PEAKS: 60,
}
JOB_IDLE_FLOOR_DEFAULT = 300

# What a kind NEEDS, when the submitter does not say. The requirements are a
# property of the WORK, so phase 0 made the submitter state them (see
# tools/jobs.py's whisper_job) -- but the three media kinds have exactly one
# right answer, it is the same on every clip, and asking every future caller
# (Timeline Cards' LibraryEngine, next) to repeat it is asking for the day one
# of them forgets `ffprobe` and a machine claims work it cannot finish. An
# explicit `requires` from the submitter always wins; this only fills a blank.
#
# `mount` takes BOTH roots the job names: reading the rush and writing the
# cache are two different filesystems here (the footage share is read-only in
# the Timeline Cards container), and a machine that has one but not the other
# is a machine that fails halfway.
_MEDIA_REQUIRES = {"ffmpeg": True, "ffprobe": True}


def default_requires(kind: str, inputs: Mapping[str, Any] | None) -> dict[str, Any]:
    """The hard requirements for a job of this kind, from its inputs. {} when
    this dashboard has no opinion (a kind it does not know, or `whisper`,
    whose VRAM floor is the submitter's to state)."""
    if str(kind) not in (db.JOB_KIND_PROXY_480P, db.JOB_KIND_AUDIO_EXTRACT,
                         db.JOB_KIND_PEAKS):
        return {}
    inputs = dict(inputs or {})
    mounts: list[str] = []
    for key in ("root", "out_root"):
        name = str(inputs.get(key) or "").strip().lower()
        if name and name not in mounts:
            mounts.append(name)
    requires = dict(_MEDIA_REQUIRES)
    if mounts:
        requires["mount"] = mounts
    return requires


# WHICH MACHINE IS PREFERRED FOR A KIND, as a table rather than a chain of
# ifs (§4.4 rule 3). Every capable machine is still offered the job in the
# end -- see RANK_GRACE_SECONDS -- so a preference can never be the reason a
# queue stops moving; it only decides who gets first refusal.
#
# Phase 4 finished the table (2026-08-30). It is now an ORDERED tuple of
# signals per kind, not a set: the first signal is worth more than the
# second, so "an encoder" beats "a GPU that is only a decoder" without
# either of them beating "is anybody sitting at it" (which is policy, not
# rank, and already refused the machine before we get here).
#
#   nvenc      the phase-1 win. The NAS container measured 11-33x realtime on
#              libx264 veryfast; a machine with an NVIDIA encoder writes the
#              same 480p proxy without spending a core on it.
#   gpu_fits   whisper's model has to fit somewhere: this machine's VRAM
#              meets the job's OWN `gpu_vram_gb` requirement with room to
#              spare. A machine that only just clears the floor still ranks,
#              below one that clears it comfortably.
#   gpu        ...and, failing that, any GPU at all.
#   near_media the machine NEXT TO THE MEDIA for the cheap I/O-bound kinds:
#              the base rig or the dashboard host. Nobody sits at it, an
#              audio copy that runs there costs an editor nothing, and the
#              round trip over SMB is what these two kinds are made of.
#   volunteering  somebody at that machine clicked "take fleet jobs now"
#              (section 10, 2026-08-30). It LEADS every kind's list because
#              it is the only signal about a PERSON: a machine whose editor
#              has said "go ahead" is a machine where the work costs nobody
#              anything, which beats any amount of hardware on a machine
#              somebody merely walked away from. It is a preference and not a
#              gate, like every other signal here -- volunteering opens the
#              idle floor in policy_refusal, and this only decides who is
#              asked first.
RANK_SIGNALS: dict[str, tuple[str, ...]] = {
    db.JOB_KIND_WHISPER: ("volunteering", "gpu_fits", "gpu"),
    db.JOB_KIND_PROXY_480P: ("volunteering", "nvenc"),
    db.JOB_KIND_AUDIO_EXTRACT: ("volunteering", "near_media"),
    db.JOB_KIND_PEAKS: ("volunteering", "near_media"),
}

# What each signal is called on the why page. An admin reading "choice 2 of 3"
# has to be able to find out WHAT the other machine had that this one has not.
SIGNAL_WORDS = {
    "volunteering": "somebody at it who said to take fleet jobs now",
    "nvenc": "an NVIDIA encoder",
    "gpu_fits": "a GPU with room for this model",
    "gpu": "a GPU",
    "near_media": "is next to the media (the base rig or the dashboard host)",
}

# How much headroom over a job's stated VRAM floor counts as "it fits". A
# model that needs 6 GB on a card with 6.0 GB free is a card that OOMs the
# moment anything else is on it, and the point of the signal is to prefer the
# machine where it will actually finish.
VRAM_HEADROOM_GB = 1.0


def is_volunteering(capabilities: Mapping[str, Any] | None,
                    now: str | None = None) -> bool:
    """Has somebody AT this machine said to take fleet jobs now? (Section 10.)

    The one lever a dashboard button deliberately does not pull: the person
    sitting at a computer is the only one who knows whether they mind their
    GPU being used while they work, so this reads a deadline their tray set
    and nothing here can set it.

    Unparseable is FALSE, the same direction `idle_seconds` takes: a value
    this server cannot read must never be the reason work starts under
    somebody's hands. An expired deadline is false too, which is what makes
    the timer running out close the gate again with no message from anyone.
    """
    raw = str((capabilities or {}).get("volunteer_until") or "")
    if not raw:
        return False
    try:
        until = db.parse_iso(raw)
        moment = db.parse_iso(now or db.utcnow_iso())
    except (TypeError, ValueError):
        log.debug("jobs: unreadable volunteer_until %r", raw)
        return False
    # A companion may spell UTC with a Z, a naive string or an offset. Naive
    # means UTC here (utcnow_iso is what the rest of this file compares
    # against), and mixing the two shapes raises inside a sort key.
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return until > moment


def _signal_true(name: str, facts: Mapping[str, Any],
                 job: Mapping[str, Any] | None) -> bool:
    """Does this machine carry this rank signal? Never raises: a capability
    that arrived as a string must not be able to throw inside a sort key."""
    caps = dict(facts.get("capabilities") or {})
    if name == "volunteering":
        return is_volunteering(caps)
    if name == "nvenc":
        return bool(caps.get("nvenc"))
    if name == "gpu":
        return bool(caps.get("gpu_present"))
    if name == "gpu_fits":
        if not caps.get("gpu_present"):
            return False
        want = (dict(job.get("requires") or {}) if job else {}).get("gpu_vram_gb")
        try:
            have = float(caps.get("gpu_vram_gb"))
        except (TypeError, ValueError):
            # A GPU that will not say how big it is fits nothing in
            # particular. Not a refusal (job_requirements_met already had its
            # say) -- just not a preference.
            return False
        if want is None:
            return True
        try:
            return have >= float(want) + VRAM_HEADROOM_GB
        except (TypeError, ValueError):
            return False
    if name == "near_media":
        return str(facts.get("mode") or "editor") == "base"
    return False


def rank_signals(
    facts: Mapping[str, Any], kind: str, job: Mapping[str, Any] | None = None,
) -> list[tuple[str, bool, int]]:
    """(signal, does this machine have it, what it is worth) for one kind."""
    names = RANK_SIGNALS.get(str(kind), ())
    return [(name, _signal_true(name, facts, job), len(names) - i)
            for i, name in enumerate(names)]


def rank_key(
    facts: Mapping[str, Any], kind: str, job: Mapping[str, Any] | None = None,
) -> tuple[float, ...]:
    """How good a home this machine is for this kind of work. BIGGER IS
    BETTER, and the order is §4.4 rule 3's: capability, then least loaded,
    then longest idle.

    Every component is a fact this dashboard already stores, and none of them
    is a tie-breaker on a name -- ranking machines alphabetically is how one
    computer ends up doing all the work of a fleet.

    `job` is optional and only the `gpu_fits` signal reads it: a caller with
    the row in hand gets the finished ranking, and one without still gets the
    kind's ordering rather than an exception.
    """
    caps = dict(facts.get("capabilities") or {})
    preference = sum(weight for _name, have, weight in rank_signals(facts, kind, job)
                     if have)
    try:
        load = float(caps.get("load"))
    except (TypeError, ValueError):
        # None means this platform has no load average (Windows). NOT a
        # penalty: it would rank every Windows machine below every Mac for a
        # reason that says nothing about how busy either is.
        load = 0.0
    try:
        idle = float(caps.get("idle_seconds"))
    except (TypeError, ValueError):
        # Unreachable in practice: policy_refusal already refused a machine
        # that cannot say. Zero here keeps the contract anyway -- an unknown
        # idle answer must never rank ABOVE a known one.
        idle = 0.0
    return (float(preference), -float(len(facts.get("live_jobs") or [])),
            -load, idle)


# The rank tuple's own field names, in order, for the explanation. A number
# in a list is not an answer to "why did the other machine win".
RANK_FIELDS = ("preference", "free_slots", "load", "idle")
RANK_FIELD_WORDS = {
    "preference": "is better placed for this kind of work",
    "free_slots": "is holding less work right now",
    "load": "is less loaded",
    "idle": "has been idle longer",
}


def why_not_first(
    mine: tuple[float, ...], best: tuple[float, ...],
    facts: Mapping[str, Any], best_facts: Mapping[str, Any],
    kind: str, job: Mapping[str, Any] | None = None,
) -> str:
    """The FIRST component this machine lost on, in words, or "".

    The whole point of phase 4's ranking being explainable: "three machines
    could take this and it went to the one without the encoder" has to be
    answerable from the why page, and a tuple of floats does not answer it.
    """
    for field, value, top in zip(RANK_FIELDS, mine, best):
        if value >= top:
            continue
        if field == "preference":
            missing = [SIGNAL_WORDS.get(name, name)
                       for (name, have, _w), (bname, bhave, _bw)
                       in zip(rank_signals(facts, kind, job),
                              rank_signals(best_facts, kind, job))
                       if bhave and not have and name == bname]
            if missing:
                return "the first choice has %s and this machine has not" % (
                    ", ".join(missing))
        return "the first choice " + RANK_FIELD_WORDS[field]
    return ""


# How long a job waits for its preferred machine before EVERY capable machine
# is offered it. A preference that could starve a queue would be worse than
# no preference at all (§6 phase 4's risk: an idle queue and a busy fleet look
# identical), and 60 s is two report intervals -- long enough for the machine
# with the encoder to have been asked twice, short enough that nobody watching
# a lane notices.
RANK_GRACE_SECONDS = 60.0

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
REFUSE_NOT_PREFERRED = "another_machine_is_preferred"
# Phase 4's three (2026-08-30).
REFUSE_FLEET_CAP = "fleet_cap"
REFUSE_COOLDOWN = "cooling_down"
REFUSE_KIND_NOT_ALLOWED = "kind_not_allowed"
REFUSE_JOBS_DISABLED = "jobs_disabled"
# Section 10's one (2026-08-30): the admin named a machine, and this is not
# it. Asked BEFORE capability and policy, because "this job is for creator-1
# only" is the whole answer for every other machine in the fleet and listing
# what else they lack would bury it.
REFUSE_NOT_TARGET = "not_the_target"

# THE JOB-LEVEL ANSWER, which is a different question from the per-machine
# one. Timeline Cards' client asks exactly one thing of `why` -- "may I stop
# waiting and make this file myself" -- and the difference between "nothing in
# this fleet can ever run this" and "every machine is busy for the next
# minute" is the difference between falling back for ever and falling back
# once. `schedulable` is the boolean it acts on; `reason_code` is why, and it
# is a CODE and not a sentence because the client branches on it.
REASON_SCHEDULABLE = ""
REASON_NO_MACHINES = "no_machine_reported"
REASON_NO_CAPABLE = "no_capable_machine"
REASON_ALL_BUSY = "all_busy"
REASON_FLEET_CAP = "fleet_cap"
REASON_HALTED = "halted"
REASON_IDLE_WAIT = "idle_wait"
REASON_COOLDOWN = "cooling_down"
REASON_NOT_ALLOWED = "kind_not_allowed"
REASON_KIND_UNKNOWN = "kind_unknown"
REASON_HELD = "held"
REASON_PINNED = "pinned"
REASON_FINISHED = "finished"
# Section 10. A targeted job has one machine's answer and one only, so the
# job-level code has to be able to say WHICH kind of nothing happened: the
# named machine is here and not free (transient -- it will run when that
# machine is), or nobody by that name has ever reported to this dashboard
# (not transient -- it will wait for ever until somebody fixes the name, or
# that machine is switched on).
REASON_TARGET_AWAY = "target_away"
REASON_TARGET_UNKNOWN = "target_unknown"

# Which job-level code a per-machine refusal counts towards. Not the identity
# map: `upgrading` and a tripped breaker are both "this machine is busy with
# its own trouble", and a client cannot do anything different about either.
REFUSAL_TO_REASON = {
    REFUSE_CAPABILITY: REASON_NO_CAPABLE,
    REFUSE_NO_CAPABILITIES: REASON_NO_CAPABLE,
    REFUSE_KIND_UNKNOWN: REASON_KIND_UNKNOWN,
    REFUSE_KIND_NOT_ALLOWED: REASON_NOT_ALLOWED,
    REFUSE_JOBS_DISABLED: REASON_NOT_ALLOWED,
    REFUSE_FLEET_HALT: REASON_HALTED,
    REFUSE_MACHINE_HALT: REASON_HALTED,
    REFUSE_UPGRADING: REASON_ALL_BUSY,
    REFUSE_BREAKER: REASON_ALL_BUSY,
    REFUSE_BUSY_WITH_JOB: REASON_ALL_BUSY,
    REFUSE_NOT_IDLE: REASON_IDLE_WAIT,
    REFUSE_COOLDOWN: REASON_COOLDOWN,
    REFUSE_FLEET_CAP: REASON_FLEET_CAP,
    REFUSE_NOT_PREFERRED: REASON_ALL_BUSY,
    # Only ever seen on a targeted job, and _blocked_reason decides between
    # `target_away` and `target_unknown` with the whole fleet in hand: this
    # map answers one machine at a time and cannot tell "the target is busy"
    # from "there is no such machine".
    REFUSE_NOT_TARGET: REASON_TARGET_AWAY,
}

# Codes that mean "wait, do not do it yourself": the fleet WILL get to it.
# Timeline Cards falls back locally on everything else, which is the safe
# direction -- a duplicate proxy costs a minute of one machine, a lane with
# no audio costs the person looking at it.
# `target_unknown` is deliberately NOT here: a job addressed to a machine
# that has never reported is a job nothing will ever take, and telling a
# client to keep waiting for it is how a lane spins for ever over a typo.
TRANSIENT_REASONS = frozenset({REASON_ALL_BUSY, REASON_FLEET_CAP,
                               REASON_IDLE_WAIT, REASON_COOLDOWN,
                               REASON_HELD, REASON_PINNED,
                               REASON_TARGET_AWAY})


def matches_target(target: str, editor: str, machine: str) -> bool:
    """Is (editor, machine) the machine this job was addressed to?

    CASE-INSENSITIVE, because the name an admin types at a terminal is the
    one they read off the fleet grid and neither is canonical. `editor/machine`
    is accepted and then BOTH halves must match: two editors' laptops can
    carry the same machine name, and a job that ran on the wrong one of them
    would be work done on a computer nobody asked about.
    """
    want = str(target or "").strip().lower()
    if not want:
        return True
    if "/" in want:
        return want == f"{str(editor).strip().lower()}/{str(machine).strip().lower()}"
    return want == str(machine).strip().lower()


def target_of(job: Mapping[str, Any] | None) -> str:
    return str((job or {}).get("target_machine") or "").strip()


def target_refusal(job: Mapping[str, Any] | None, editor: str,
                   machine: str) -> tuple[str, str]:
    """("", "") unless this job is addressed to somebody else."""
    target = target_of(job)
    if not target or matches_target(target, editor, machine):
        return "", ""
    return REFUSE_NOT_TARGET, f"this job is for {target} only"


def fleet_caps(settings: Any = None) -> dict[str, int]:
    """How many of each kind may be in flight across the fleet at once.

    `db.JOB_MAX_RUNNING` unless this deployment overrode it
    (DASH_JOBS_MAX_RUNNING): "how many ffmpegs the media share can feed" is a
    fact about somebody's network, and this code has no way to know it.
    """
    caps = dict(db.JOB_MAX_RUNNING)
    caps.update(dict(getattr(settings, "jobs_max_running", None) or {}))
    return caps


def max_running(kind: str, caps: Mapping[str, int] | None = None) -> int:
    table = dict(caps) if caps is not None else dict(db.JOB_MAX_RUNNING)
    try:
        return max(1, int(table.get(str(kind), db.JOB_MAX_RUNNING_DEFAULT)))
    except (TypeError, ValueError):
        return db.JOB_MAX_RUNNING_DEFAULT


def can_pin(app: Any = None) -> bool:
    """Is there an executor in this container at all? (§4.4 rule 5.)

    The answer decides between `pinned` and `abandoned` for a job whose retry
    budget is gone, and it must be FALSE by default: a job pinned into a
    queue nothing drains is worse than an abandoned one, because an abandoned
    one is visible and says so.
    """
    executor = getattr(getattr(app, "state", None), "pinned_executor", None)
    try:
        return bool(executor is not None and executor.available())
    except Exception:                                              # noqa: BLE001
        log.debug("jobs: could not ask the pinned executor", exc_info=True)
        return False


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
        "SELECT mode, halt_active, breaker_tripped, jobs_cooldown_until, "
        "       jobs_cooldown_reason FROM machine_state "
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
        "cooldown_until": (str(row["jobs_cooldown_until"] or "")
                           if row is not None else ""),
        "cooldown_reason": (str(row["jobs_cooldown_reason"] or "")
                            if row is not None else ""),
    }


def fleet_facts(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    """policy()'s answer for EVERY machine, in five queries.

    machine_facts is the honest per-machine read and stays the one the claim
    route uses (it re-checks against the capabilities in the request). This is
    the bulk form, and it exists because ranking is a question about the
    fleet: "is anyone better placed for this job than the machine that just
    reported" cannot be answered one row at a time, and doing it with
    machine_facts in a loop would put five queries per machine per job on the
    path every report of every machine takes (the N+1 that commit 6f14dd2
    already had to take out of the capabilities map).
    """
    caps_map = db.fetch_capabilities_map(conn)
    halted = bool(db.get_fleet_halt(conn)["active"])
    upgrading = {
        (row["editor_username"], row["machine"])
        for row in conn.execute(
            "SELECT editor_username, machine FROM machines "
            " WHERE update_requested_version IS NOT NULL "
            "   AND update_requested_version != ''")
    }
    live: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in conn.execute(
        "SELECT id, kind, claimed_by, claimed_machine FROM jobs "
        " WHERE state IN (?, ?) ORDER BY id", db.JOB_HELD_STATES
    ):
        live.setdefault((row["claimed_by"] or "", row["claimed_machine"] or ""),
                        []).append({"id": row["id"], "kind": row["kind"]})
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT editor_username, machine, mode, halt_active, breaker_tripped, "
        "       jobs_cooldown_until, jobs_cooldown_reason "
        "  FROM machine_state ORDER BY editor_username, machine"
    ):
        key = (row["editor_username"], row["machine"])
        out[key] = {
            "editor": key[0], "machine": key[1],
            "capabilities": caps_map.get(key, {}),
            "mode": (row["mode"] or "editor"),
            "halt_active": bool(row["halt_active"]),
            "breaker_tripped": bool(row["breaker_tripped"]),
            "upgrading": key in upgrading,
            "live_jobs": live.get(key, []),
            "fleet_halt": halted,
            "cooldown_until": str(row["jobs_cooldown_until"] or ""),
            "cooldown_reason": str(row["jobs_cooldown_reason"] or ""),
        }
    return out


def ranked_machines(
    job: Mapping[str, Any], fleet: Mapping[tuple[str, str], Mapping[str, Any]],
    now: str | None = None,
) -> list[tuple[tuple[str, str], tuple[float, ...]]]:
    """Every machine that could take this job right now, best first.

    Capability AND policy, because a preference for a machine that is halted
    is not a preference, it is a stall. A TARGETED job (section 10) ranks the
    one machine it names and nobody else, which is what makes `--on` mean
    what it says even inside the grace window.
    """
    kind = str(job["kind"])
    able: list[tuple[tuple[str, str], tuple[float, ...]]] = []
    for key, facts in fleet.items():
        ok, _why = db.job_requirements_met(job.get("requires"), facts["capabilities"])
        if not ok:
            continue
        if target_refusal(job, key[0], key[1])[0]:
            continue
        reason, _sentence = policy_refusal(facts, kind, now, job)
        if reason:
            continue
        able.append((key, rank_key(facts, kind, job)))
    able.sort(key=lambda pair: pair[1], reverse=True)
    return able


def job_age_seconds(job: Mapping[str, Any], now: str) -> float:
    """How long this job has been waiting. 0 when either timestamp is
    unreadable -- which makes the grace period expire IMMEDIATELY rather than
    never, because a preference that outlives a broken clock is a queue that
    stops."""
    try:
        return max(0.0, (db.parse_iso(now)
                         - db.parse_iso(str(job["created_at"]))).total_seconds())
    except Exception:
        log.debug("jobs: unreadable timestamps on job #%s", job.get("id"),
                  exc_info=True)
        return RANK_GRACE_SECONDS


def first_refusal(
    job: Mapping[str, Any], key: tuple[str, str],
    fleet: Mapping[tuple[str, str], Mapping[str, Any]], now: str,
) -> bool:
    """May THIS machine be offered this job yet? (§4.4 rule 3.)

    Rank is a preference and never a gate: past RANK_GRACE_SECONDS every
    capable machine is offered the job, so the worst a wrong preference can
    cost is a minute. Ties are offered TOGETHER -- two machines with the same
    encoder are equally right, and the compare-and-set is what decides between
    them, which is the whole reason the claim is a CAS.

    A FORCED OR TARGETED JOB HAS NO GRACE WINDOW (section 10). Forced means
    "do not wait", and waiting sixty seconds for a better-placed machine is
    the one thing the admin said not to do; targeted means there is only one
    candidate, so a preference among candidates has nothing left to decide.
    """
    if job.get("forced") or target_of(job):
        return True
    if job_age_seconds(job, now) >= RANK_GRACE_SECONDS:
        return True
    able = ranked_machines(job, fleet, now)
    if not able:
        return True
    best = able[0][1]
    return any(k == key for k, score in able if score == best)


def policy_refusal(facts: Mapping[str, Any], kind: str,
                   now: str | None = None,
                   job: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """Why this machine may take no job of this kind right now, or ("", "").

    Order matters: the first true answer is the one shown, and it is the
    order an admin would ask the questions in -- is everything stopped, is
    this machine stopped, is it in the middle of something, is anyone sitting
    at it.

    `job` is optional and only the last two questions read it (section 10).
    WHAT A FORCED JOB SKIPS IS A SHORT LIST AND THIS IS ALL OF IT: the
    cooldown and the idle floor. A fleet halt, a machine halt, an update
    waiting, a tripped breaker, a job already held, `jobs_enabled` and the
    machine's own kind allow-list are all still refusals, because "do not
    wait for anybody to leave their desk" is not "run on a machine that
    cannot". A volunteer opens the idle floor only: somebody said this work
    may run while they are here, not that their broken ffmpeg should be
    tried again.
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
    if not caps.get("jobs_enabled", True):
        return (REFUSE_JOBS_DISABLED,
                "fleet jobs are switched off on this machine (jobs_enabled)")
    # THE MACHINE'S OWN ALLOW-LIST (v45, phase 4). Its own refusal and not
    # folded into the capability one: "this laptop does not do whisper" is a
    # setting somebody chose, and "this laptop has no GPU" is a fact about
    # the hardware. An admin looking at the why page can act on the first.
    if not db.machine_allows_kind(caps, kind):
        return (REFUSE_KIND_NOT_ALLOWED,
                f"this machine's config allows only "
                f"{', '.join(caps.get('job_kinds') or [])} jobs, not {kind}")
    # ...AND A MACHINE THAT JUST FAILED ONE IS LEFT ALONE. Without this the
    # machine with the broken ffmpeg is first in the queue for the retry
    # every time -- failing in two seconds is exactly what keeps it idle --
    # and one bad machine spends a two-attempt budget on its own.
    forced = bool((job or {}).get("forced"))
    until = str(facts.get("cooldown_until") or "")
    if until and until > (now or db.utcnow_iso()) and not forced:
        reason = str(facts.get("cooldown_reason") or "a job failed here")
        return (REFUSE_COOLDOWN,
                f"this machine is cooling down until {until} ({reason})")
    # THE BASE RIG IS EXEMPT (MULTI_MACHINE_PLAN.md WP0): nobody sits at it,
    # and idle.py on a machine with no console session cannot answer anyway.
    # ...AND THE TWO WAYS PAST THE IDLE FLOOR (section 10): the person at
    # the machine said to take work now, or the admin who submitted this job
    # said not to wait for anybody. Both are somebody choosing, on purpose,
    # to have work run with an editor present -- which is the one thing the
    # floor exists to prevent, so nothing else may skip it.
    if (str(facts.get("mode") or "editor") != "base"
            and not forced and not is_volunteering(caps, now)):
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
    caps: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """What this machine may claim right now.

    -> {"offered": [job ids], "forced": [job ids]}, plus "refused"
    (id -> reason) for the log and the why page. The list is SMALL on
    purpose: it rides every report of every machine in the fleet, and a
    companion claims one job at a time anyway.

    `forced` is the subset of `offered` whose row carries the admin's "now"
    (section 10). It rides the reply as its own key because the COMPANION has
    a gate of its own -- its user_active and resolve_open checks -- and an id
    on the `offered` list alone tells it nothing about whether the person who
    submitted the job meant to interrupt somebody. A companion older than
    0.9.61 ignores the key and claims on its own gate exactly as before.

    The same job is offered to every machine that could do it, EXCEPT for the
    first RANK_GRACE_SECONDS, when it is offered to the best-placed machines
    only (§4.4 rule 3, phase 1). That is still "offer, don't push": the
    compare-and-set decides, a tie is offered to both, and a fleet where one
    machine's reply was lost still gets the work done a minute later.
    """
    now = now or db.utcnow_iso()
    facts = machine_facts(conn, editor, machine, capabilities)
    key = (editor, machine)
    fleet: dict[tuple[str, str], Any] | None = None
    offered: list[int] = []
    forced: list[int] = []
    refused: dict[int, str] = {}
    # THE FLEET CAP IS COUNTED ONCE, not per job: it is a fact about the
    # whole queue and this runs on every report of every machine. `running`
    # is incremented as offers are made in this same pass, because eight
    # offers of a capped kind on one reply is exactly the burst the cap
    # exists to stop.
    running = db.count_running_by_kind(conn)
    for job in db.queued_jobs(conn):
        kind = str(job["kind"])
        if kind not in db.JOB_KINDS:
            refused[int(job["id"])] = REFUSE_KIND_UNKNOWN
            continue
        if running.get(kind, 0) >= max_running(kind, caps):
            refused[int(job["id"])] = REFUSE_FLEET_CAP
            continue
        # THE ADMIN NAMED A MACHINE, and this is not it (section 10). Asked
        # before capability and policy because it is the whole answer: what
        # else this machine lacks is not interesting about a job it may never
        # be offered.
        if target_refusal(job, editor, machine)[0]:
            refused[int(job["id"])] = REFUSE_NOT_TARGET
            continue
        ok, _why = db.job_requirements_met(job.get("requires"), facts["capabilities"])
        if not ok:
            refused[int(job["id"])] = REFUSE_CAPABILITY
            continue
        reason, _sentence = policy_refusal(facts, kind, now, job)
        if reason:
            refused[int(job["id"])] = reason
            continue
        if fleet is None:
            # LAZY, and once: the ranking pass costs five queries, and the
            # commonest report by far is one with nothing to offer at all.
            # THIS machine's row is replaced by the facts above, which carry
            # the capabilities that arrived with this very request rather than
            # the ones stored a report interval ago.
            fleet = dict(fleet_facts(conn))
            fleet[key] = facts
        if not first_refusal(job, key, fleet, now):
            refused[int(job["id"])] = REFUSE_NOT_PREFERRED
            continue
        offered.append(int(job["id"]))
        if job.get("forced"):
            forced.append(int(job["id"]))
        running[kind] = running.get(kind, 0) + 1
        if len(offered) >= max(1, int(limit)):
            break
    return {"offered": offered, "forced": forced, "refused": refused}


def explain(conn: sqlite3.Connection, job_id: int,
            caps: Mapping[str, int] | None = None,
            now: str | None = None) -> dict[str, Any] | None:
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
    now = now or db.utcnow_iso()
    kind = str(job["kind"])
    lines: list[dict[str, Any]] = []
    if (job["state"] in db.JOB_TERMINAL_STATES
            or job["state"] in db.JOB_HELD_STATES
            or job["state"] == db.JOB_PINNED):
        # Not a scheduling question any more. Say so rather than listing
        # eight machines that "could have".
        return {
            "job": job, "schedulable": False, "machines": [],
            "reason_code": _terminal_reason(job),
            "summary": _terminal_summary(job),
        }
    fleet = fleet_facts(conn)
    able = ranked_machines(job, fleet, now)
    order = {key: rank for rank, (key, _score) in enumerate(able, start=1)}
    scores = dict(able)
    best_key, best_score = (able[0] if able else (None, ()))
    for (editor, machine), facts in fleet.items():
        reason, sentence = target_refusal(job, editor, machine)
        if reason:
            lines.append({"editor": editor, "machine": machine, "ok": False,
                          "reason": reason, "why": sentence})
            continue
        ok, why = db.job_requirements_met(job.get("requires"), facts["capabilities"])
        if not ok:
            lines.append({"editor": editor, "machine": machine, "ok": False,
                          "reason": REFUSE_CAPABILITY, "why": why})
            continue
        reason, sentence = policy_refusal(facts, kind, now, job)
        if reason:
            lines.append({"editor": editor, "machine": machine, "ok": False,
                          "reason": reason, "why": sentence})
            continue
        # ok, and WHERE IN THE ORDER -- because "three machines can take this
        # and it went to the one without the encoder" is a scheduling
        # complaint this page has to be able to answer.
        key = (editor, machine)
        rank = order.get(key, 0)
        score = scores.get(key, ())
        # THE RANK TUPLE ITSELF RIDES ALONG (phase 4). A sentence is what an
        # admin reads and the numbers are what a bug report is made of: the
        # complaint "it went to the machine without the encoder" is only
        # answerable if the four components that decided it are visible.
        line = {"editor": editor, "machine": machine, "ok": True,
                "reason": "", "rank": rank,
                "score": [round(float(v), 3) for v in score],
                "signals": {name: have
                            for name, have, _w in rank_signals(facts, kind, job)}}
        if rank == 1:
            line["why"] = "this machine can take it, and is first choice"
            line["why_not_first"] = ""
        else:
            beaten = why_not_first(score, best_score, facts,
                                   fleet.get(best_key) or {}, kind, job)
            line["why_not_first"] = beaten
            line["why"] = (f"this machine can take it (choice {rank} of "
                           f"{len(order)}"
                           + (f"; {beaten}" if beaten else "")
                           + f"; it is offered the job anyway once it has "
                             f"waited {int(RANK_GRACE_SECONDS)}s)")
        lines.append(line)
    can = [m for m in lines if m["ok"]]
    # The fleet cap is a property of the QUEUE, not of any machine, so it is
    # asked here rather than in policy_refusal: every machine could take this
    # job, and the answer is still "not yet".
    live = db.count_running_by_kind(conn).get(kind, 0)
    cap = max_running(kind, caps)
    capped = kind in db.JOB_KINDS and live >= cap
    if kind not in db.JOB_KINDS:
        code = REASON_KIND_UNKNOWN
        summary = (f"this dashboard does not know the job kind {kind!r}, so no "
                   f"machine will ever be offered it")
    elif capped:
        code = REASON_FLEET_CAP
        summary = (f"{live} {kind} job(s) are already running, which is this "
                   f"fleet's limit ({cap}); it starts as soon as one finishes")
    elif can:
        code = REASON_SCHEDULABLE
        summary = (f"{len(can)} machine(s) can take this job; it is waiting to "
                   f"be claimed on their next report")
    elif not lines:
        code = REASON_NO_MACHINES
        summary = "no machine has ever reported to this dashboard"
    else:
        code = _blocked_reason(lines, job)
        summary = _blocked_summary(lines, job)
    return {"job": job,
            # UNCHANGED MEANING (phase 1): "is anything going to take this,
            # soon". Timeline Cards' client makes the file itself when this
            # is false, and that is still the right answer for a fleet whose
            # every machine has somebody sitting at it.
            "schedulable": bool(can) and kind in db.JOB_KINDS and not capped,
            # ...and the code is what tells the two kinds of false apart
            # (phase 4): `no_capable_machine` will still be true in an hour,
            # `all_busy` will not.
            "reason_code": code,
            "transient": code in TRANSIENT_REASONS,
            # How many machines could EVER run this, ignoring who is at their
            # desk right now. The number an admin needs before buying a GPU.
            # A TARGETED job can only ever run on one machine, so the
            # machines that refused for being somebody else are not "could
            # EVER run this" -- counting them would answer an admin's "do I
            # need to buy a GPU" with a number about a job addressed
            # elsewhere.
            "capable": sum(1 for m in lines
                           if m["reason"] not in (REFUSE_CAPABILITY,
                                                  REFUSE_NO_CAPABILITIES,
                                                  REFUSE_KIND_NOT_ALLOWED,
                                                  REFUSE_JOBS_DISABLED,
                                                  REFUSE_NOT_TARGET)),
            "running": live, "cap": cap,
            "machines": lines, "summary": summary}


def _terminal_reason(job: Mapping[str, Any]) -> str:
    state = str(job["state"])
    if state in db.JOB_HELD_STATES:
        return REASON_HELD
    if state == db.JOB_PINNED:
        return REASON_PINNED
    return REASON_FINISHED


def _blocked_reason(lines: list[dict[str, Any]],
                    job: Mapping[str, Any] | None = None) -> str:
    """The job-level code, from the per-machine refusals.

    THE WORST ANSWER WINS, not the commonest: one machine that could do this
    if its editor stood up is a fleet that will get to it, and answering
    "no_capable_machine" because four other machines have no GPU would send
    the client off to do GPU work on a laptop.

    A TARGETED job (section 10) is answered by the machine it names and by
    nobody else: "four machines are busy" is not an answer about work only
    one of them may do. The worst-answer rule is unchanged -- it simply runs
    over that machine's lines. When its own refusal is one a client can wait
    out, the code is `target_away`, because what a waiting client needs to
    know is that it is waiting for ONE computer; when it is not (no such
    capability, halted, kind not allowed) that answer passes straight
    through, because a client must never be told to wait for something that
    is never going to happen.
    """
    target = target_of(job)
    if target:
        mine = [line for line in lines if line["reason"] != REFUSE_NOT_TARGET]
        if not mine:
            return REASON_TARGET_UNKNOWN
        code = _blocked_reason(mine)
        return REASON_TARGET_AWAY if code in TRANSIENT_REASONS else code
    codes = {REFUSAL_TO_REASON.get(line["reason"], REASON_NO_CAPABLE)
             for line in lines}
    for code in (REASON_ALL_BUSY, REASON_FLEET_CAP, REASON_COOLDOWN,
                 REASON_IDLE_WAIT, REASON_HALTED, REASON_NOT_ALLOWED,
                 REASON_KIND_UNKNOWN):
        if code in codes:
            return code
    return REASON_NO_CAPABLE


def _terminal_summary(job: Mapping[str, Any]) -> str:
    state = str(job["state"])
    if state in db.JOB_HELD_STATES:
        return (f"{job['claimed_by']}/{job['claimed_machine']} is holding this "
                f"job (lease until {job['lease_expires_at']})")
    if state == db.JOB_PINNED:
        return ("the fleet could not finish this, so it is pinned to the "
                "dashboard's own worker; it never goes back to the fleet")
    if state == db.JOB_DONE:
        return "this job is done"
    if state == db.JOB_ABANDONED:
        return (f"given up after {job['attempts']} attempt(s): "
                f"{job['last_error'] or 'no error recorded'}")
    return f"this job failed and will not be retried: {job['last_error']}"


def _blocked_summary(lines: list[dict[str, Any]],
                     job: Mapping[str, Any] | None = None) -> str:
    """One sentence naming the COMMONEST reason, because that is the one
    thing an admin can act on ("everyone is at their desk" is a different
    action from "nobody has a GPU")."""
    target = target_of(job)
    if target:
        # The named machine's own answer, or the fact that there is no such
        # machine -- which is the one thing an admin who mistyped a name
        # needs to read, and it would otherwise appear as "5 of 5 machines
        # are not the target".
        mine = [line for line in lines if line["reason"] != REFUSE_NOT_TARGET]
        if not mine:
            return (f"this job is for {target} only, and no machine of that "
                    f"name has ever reported to this dashboard")
        line = mine[0]
        return (f"this job is for {target} only, and it cannot take it: "
                f"{line.get('why') or line['reason']}")
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
        REFUSE_NOT_PREFERRED: "are waiting for a better-placed machine",
        REFUSE_COOLDOWN: "are cooling down after failing a job",
        REFUSE_KIND_NOT_ALLOWED: "are not allowed this kind of work",
        REFUSE_JOBS_DISABLED: "have fleet jobs switched off",
        REFUSE_FLEET_CAP: "are at this fleet's limit for the kind",
        REFUSE_NOT_TARGET: "are not the machine this job was sent to",
    }.get(reason, reason)
    return (f"no machine can take this job right now: {count} of {len(lines)} "
            f"{words}")
