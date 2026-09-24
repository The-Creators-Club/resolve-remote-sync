"""The server triage agent: a twice-daily, READ-ONLY Claude Code review of
everything this dashboard knows is open, stuck or failing, mailed to the owner
with suggested actions a reply can carry out.

2026-09-24, docs/SERVER_TRIAGE_AGENT.md. The owner's decisions, which this
module does not second-guess:

  * the scheduled run is READ-ONLY. Claude Code gets Read, Grep and Glob over
    a scrubbed evidence file and this package's own source, and nothing else:
    every writing, executing or fetching tool is named in --disallowedTools.
    It proposes; `triage_actions` is the only thing that ever acts, and only
    on an authenticated reply (`triage_mail`).
  * 06:00 and 18:00 in the site's zone (`alerts_timezone`, which the studio
    sets to Asia/Taipei on deploy).
  * ALWAYS SEND. A run with nothing to say mails an all-clear, and a run whose
    analysis fails mails a fallback made in code from the same evidence: the
    only sign of a dead agent the owner is promised is an absent email, so the
    agent's own failure must be an email and not a log line.

The schedule is `alerts.weekly_due`'s, generalised to several hours a day:
DURABLE, from the `alert_log` ledger, never a timer. A container restarted at
05:59 runs it once, one down at 06:00 runs it late, six restarts do not run
it six times, and `alerts._retry_due`'s backoff bounds a dead channel.

The run takes minutes and must never hold the collector thread (the collector
watchdog replaces a container whose cycle stalls), so `maybe_start` only
decides and starts a DAEMON THREAD with its own connection. One run at a
time: a module lock plus a `meta` row, and a row older than 90 minutes is a
dead run, not a live one.

The Anthropic API provider is deliberately NOT a fallback: the run needs
Claude Code's read-only file tools, which the SDK path does not have. Nothing
is bundled (COMMERCIAL_READINESS item 1); the CLI is the one the admin
installed through Settings -> AI providers, run through `cli_tools.cli_env`
exactly as `cards_ai.Runner._cli` runs it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

from . import ai_providers, alerts, cards_ai, cli_tools, db, triage_actions, triage_mail

log = logging.getLogger("ccsync.dashboard.triage")

# The alert_log kinds. `triage` is the one the schedule reads (ok=1 means the
# report went out); the confirmation of a reply is its own kind so it can
# never satisfy a slot.
KIND_TRIAGE = "triage"
KIND_REPLY = "triage_reply"
LEDGER_SUBJECT = "server check"

SUBJECT_PREFIX = "[CC Sync] Server check"

META_RUNNING = "triage_running_since"
RUN_STALE_SECONDS = 90 * 60
TOKEN_TTL_SECONDS = 48 * 3600
KEEP_DAYS = 60
CLI_TIMEOUT_SECONDS = 20 * 60
POLL_SECONDS = 120.0
EVIDENCE_ALERT_HOURS = 48

# The family alias, CR-309: `cards_ai.cli_model_arg` sends it as `opus`, so
# the check follows the newest Opus the installed CLI knows.
TRIAGE_MODEL = "claude-opus-5-5"
READ_TOOLS = "Read,Grep,Glob"
DENIED_TOOLS = "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task"

MAX_FINDINGS = 30
MAX_ACTIONS = 20
MAX_TEXT = 4000

_EM_DASH = chr(0x2014)


class TriageError(Exception):
    """The analysis could not be had. The message is the reason the fallback
    email gives, so it is written for the owner, never carries a secret."""


# ------------------------------------------------------------------ text

def plain(value: Any) -> str:
    """A string for the email, with the owner's no-em-dash rule applied to
    anything the model wrote."""
    return str(value if value is not None else "").replace(_EM_DASH, " - ").strip()


def _one_line(value: Any, limit: int = 150) -> str:
    return re.sub(r"\s+", " ", plain(value))[:limit]


def local_time(conn: sqlite3.Connection, iso: str) -> str:
    zone, name = alerts._zone_or_utc(conn)
    try:
        when = db.parse_iso(iso)
    except (ValueError, TypeError):
        return str(iso)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(zone).strftime("%Y-%m-%d %H:%M ") + name


def data_dir(settings: Any) -> Path:
    return Path(str(getattr(settings, "db_path", "") or ".")).parent


def _run_dir(settings: Any, run_id: int) -> Path:
    return data_dir(settings) / "triage" / str(int(run_id))


def _iso_plus(now: str, seconds: float) -> str:
    return (db.parse_iso(now) + dt.timedelta(seconds=seconds)).isoformat()


# -------------------------------------------------------------- the schedule

def parse_hours(raw: str) -> list[int]:
    try:
        hours = sorted({int(p) for p in str(raw or "").split(",") if p.strip()})
    except ValueError:
        hours = []
    hours = [h for h in hours if 0 <= h <= 23]
    return hours or [6, 18]


def previous_slot(now: dt.datetime, zone, hours: list[int]) -> dt.datetime:
    """The most recent of `hours` (today or yesterday, IN `zone`) at or before
    `now`, as an aware UTC datetime. From the local calendar, as
    `alerts.previous_weekly_slot` is, so a DST change does not move it."""
    local = now.astimezone(zone)
    best: dt.datetime | None = None
    for days_back in (0, 1):
        day = local.date() - dt.timedelta(days=days_back)
        for hour in hours:
            slot = dt.datetime.combine(day, dt.time(hour, 0), tzinfo=zone)
            if slot <= local and (best is None or slot > best):
                best = slot
    if best is None:                      # unreachable with 1+ hours; defensive
        best = dt.datetime.combine(local.date() - dt.timedelta(days=1),
                                   dt.time(hours[-1], 0), tzinfo=zone)
    return best.astimezone(dt.timezone.utc)


def triage_due(conn: sqlite3.Connection, now: str) -> bool:
    """Whether a check is owed: `alerts.weekly_due`'s rule over several hours
    a day. Off, or with no channel to send it through, is never due: the run
    costs a Claude Code session and a report nobody can receive is not worth
    one."""
    values = alerts.get_settings(conn)
    if (values.get("alerts_triage") or "0") != "1":
        return False
    if (values.get("alerts_sink") or alerts.SINK_NONE) == alerts.SINK_NONE:
        return False
    zone, _name = alerts._zone_or_utc(conn)
    try:
        now_dt = db.parse_iso(now)
    except (ValueError, TypeError):
        return False
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=dt.timezone.utc)
    slot = previous_slot(now_dt, zone, parse_hours(values.get("alerts_triage_hours", "")))
    if not alerts._retry_due(conn, KIND_TRIAGE, slot.isoformat(), now):
        return False
    last = db.last_alert_at(conn, KIND_TRIAGE, ok_only=True)
    if not last:
        return True
    try:
        last_dt = db.parse_iso(last)
    except (ValueError, TypeError):
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=dt.timezone.utc)
    return last_dt < slot


# ------------------------------------------------------------------ the gate

def cli_gate(conn: sqlite3.Connection, settings: Any) -> tuple[str, str]:
    """(the Claude Code executable, "") or ("", why not). The door is the
    site's `ai_cli_providers` feature AND an executable `ai_providers` can
    find; either missing makes the run a fallback email that says which."""
    from . import site_store

    if not site_store.feature_enabled(conn, settings, "ai_cli_providers"):
        return "", ("Claude Code is switched off on this server (the site feature "
                    "ai_cli_providers)")
    path = ai_providers.cli_path(conn, ai_providers.CLAUDE_CODE, settings)
    if not path:
        return "", "Claude Code is not installed on this server (Settings, AI providers)"
    return path, ""


# ------------------------------------------------------------ the CLI call

def build_argv(cli: str, model_arg: str, package_dir: str) -> list[str]:
    """The scheduled run's argv. Read-only by construction: the three reading
    tools allowed, every writing/executing/fetching tool denied by name."""
    return [cli, "-p", "--output-format", "json", "--model", model_arg,
            "--allowedTools", READ_TOOLS,
            "--disallowedTools", DENIED_TOOLS,
            "--add-dir", str(package_dir)]


def _spawn(argv: list[str], prompt: str, cwd: str, env: dict,
           timeout: float) -> subprocess.CompletedProcess:
    """The one subprocess seam, so the suite never runs a real CLI."""
    return subprocess.run(  # noqa: S603 - argv, never a shell
        argv, input=prompt, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=float(timeout), env=env, cwd=cwd)


def run_cli(argv: list[str], prompt: str, *, cwd: str, timeout: float,
            settings: Any) -> str:
    env = cli_tools.cli_env(settings, ai_providers.CLAUDE_CODE)
    try:
        proc = _spawn(argv, prompt, cwd, env, timeout)
    except subprocess.TimeoutExpired:
        raise TriageError(f"Claude Code did not answer within "
                          f"{int(timeout // 60) or 1} minute(s)") from None
    except (OSError, ValueError) as exc:
        raise TriageError(f"Claude Code could not be started ({type(exc).__name__}: "
                          f"{str(exc)[:160]})") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise TriageError(f"Claude Code exited {proc.returncode}: {detail}")
    return proc.stdout or ""


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def parse_report(stdout: str) -> dict[str, Any]:
    """The ONE JSON object out of the CLI's answer: the envelope first
    (`cards_ai._cli_reply`), then the object in its `result`, tolerating a
    fenced block or prose around it."""
    reply = cards_ai._cli_reply(stdout)
    if reply is None:
        text = stdout or ""
    else:
        said = reply.get("result")
        text = said if isinstance(said, str) else ""
        if reply.get("is_error"):
            raise TriageError(f"Claude Code reported an error: {text.strip()[:300]}")
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise TriageError("the analysis did not answer with the JSON object it was "
                      "asked for: " + _one_line(text[-200:], 200))


# ------------------------------------------------------------ the evidence

_SECRET_KEY_RE = re.compile(r"password|passwd|token|secret|api_?key", re.I)
_SECRET_VALUE_RES = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"cce1\.[A-Za-z0-9._-]+"),
    re.compile(r"ghp_\w+"),
)
REDACTED = "[redacted]"


def _scrub_obj(value: Any) -> Any:
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key) and item not in (None, "", False):
                out[key] = REDACTED
            else:
                out[key] = _scrub_obj(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub_obj(v) for v in value]
    return value


def scrub_text(text: str) -> str:
    for pattern in _SECRET_VALUE_RES:
        text = pattern.sub(REDACTED, text)
    return text


def _json_default(value: Any) -> Any:
    if hasattr(value, "keys"):
        try:
            return {k: value[k] for k in value.keys()}
        except Exception:                                           # noqa: BLE001
            pass
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)


def scrub(bundle: Mapping[str, Any]) -> str:
    """The bundle as the JSON the CLI reads, with every field whose NAME says
    secret emptied and every value that LOOKS like a key (sk-..., cce1...,
    ghp_...) replaced, over the serialised text so nothing nested escapes."""
    text = json.dumps(_scrub_obj(json.loads(json.dumps(bundle, default=_json_default))),
                      indent=1, sort_keys=True, ensure_ascii=False)
    return scrub_text(text)


def _jobs_section(conn: sqlite3.Connection) -> dict[str, Any]:
    open_jobs = db.list_jobs(conn, state="open", limit=500)
    counts = Counter(f"{j.get('kind')}/{j.get('state')}" for j in open_jobs)
    return {"open": open_jobs, "counts": dict(sorted(counts.items()))}


def previous_outcomes(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, started_at, status FROM triage_runs WHERE finished_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return {"run": None, "actions": []}
    actions = [
        {"n": r["n"], "action": r["action"], "params": r["params_json"],
         "state": r["state"], "result": r["result"], "acted_at": r["acted_at"]}
        for r in conn.execute("SELECT * FROM triage_actions WHERE run_id=? ORDER BY n",
                              (int(row["id"]),))]
    return {"run": dict(row), "actions": actions}


def build_bundle(conn: sqlite3.Connection, settings: Any, now: str) -> dict[str, Any]:
    """Everything the check reads, from readers that already exist. Each
    section is its own try: a reader that raises becomes {"error": ...} in
    that section, never a failed run. Nothing from site_settings or
    <data>/secrets is read here."""
    from . import api, invariants

    since = (db.parse_iso(now) - dt.timedelta(hours=EVIDENCE_ALERT_HOURS)).isoformat()
    readers: dict[str, Callable[[], Any]] = {
        "open_notices": lambda: db.open_notices(conn, limit=200),
        "alert_log_48h": lambda: db.fetch_alerts(conn, limit=500, since=since),
        "open_alert_counts": lambda: db.meta_get_json(conn, db.META_ALERTS_OPEN),
        "invariants": lambda: invariants.page_view(conn),
        "collector": lambda: db.fetch_collector_status(conn, now=now, settings=settings),
        "fleet": lambda: api.build_editors_view(conn, now),
        "transfers": lambda: api.build_transfers_view(conn, now),
        "jobs": lambda: _jobs_section(conn),
        "packages": lambda: api.build_packages_view(conn, settings, now),
        "previous_run": lambda: previous_outcomes(conn),
    }
    bundle: dict[str, Any] = {"generated_at": now,
                              "timezone": alerts.timezone_name(conn)}
    for name, reader in readers.items():
        try:
            bundle[name] = reader()
        except Exception as exc:                                    # noqa: BLE001
            log.warning("triage: evidence section %s could not be read: %s", name, exc)
            bundle[name] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
    return bundle


# -------------------------------------------------------------- the prompt

TRIAGE_PROMPT = """You are reviewing the server of a video-sync fleet: CC Sync, a dashboard on a NAS that keeps several editors' computers syncing footage through it. You are READ-ONLY. You can read files; you never change anything, and nothing you write is carried out except by the owner's reply choosing from the catalogue below.

Read evidence.json in the current directory. It is everything the dashboard knows right now that is open, stuck or failing: open notices, the last 48 hours of alerts, the invariant checks, the collector's health, every computer's state on the fleet grid (version, lanes, why it is not syncing, its guard: stalls, crashes, blocked reason, breaker, halt, refused upgrades), live transfers and the queue, open fleet jobs, the packages each computer runs against the current builds, and what became of the actions the previous check offered (do not suggest again what was just done or refused unless the evidence says it did not work). A section that could not be read says {"error": ...}; say so if it matters.

The source code of the running dashboard is in the added directory ({package_dir}). Read it when you need to know what a field, a notice or a state means.

Say what needs a person, most important first, each with its evidence and a suggested action. Do not list what is fine. A computer with no projects ticked is never a problem. If nothing needs a person, set all_clear to true and leave findings empty.

Suggest actions ONLY from this catalogue, with exactly these parameter names, and the editor and machine exactly as the evidence spells them:

{catalogue}

A code defect is a finding with a code_fix_prompt (a paste-ready prompt for a Claude Code session in the ccsync repo, naming the files and the evidence), never an action. Anything else a person must do by hand is a finding's suggestion, in plain words for a non-technical owner.

Write plain text in every string: no markdown, no em dashes.

Answer with ONE JSON object and nothing else:
{"subject": "...", "headline": "...", "all_clear": false,
 "findings": [{"title": "...", "severity": "error|warn|info",
               "evidence": "...", "suggestion": "...",
               "action_refs": [1], "code_fix_prompt": ""}],
 "actions": [{"n": 1, "action": "resume_breaker",
              "params": {"editor": "...", "machine": "..."},
              "why": "..."}]}
"""


def render_prompt(package_dir: str) -> str:
    # str.replace, not format: the prompt is full of JSON braces.
    return (TRIAGE_PROMPT.replace("{package_dir}", str(package_dir))
            .replace("{catalogue}", triage_actions.catalogue_for_prompt()))


# ------------------------------------------------------- the model's answer

def clean_report(data: Mapping[str, Any]) -> dict[str, Any]:
    """The answer in the shape the email is built from, whatever the model
    sent: strings are strings, lists are bounded, a severity is one of three."""
    findings = []
    for item in list(data.get("findings") or [])[:MAX_FINDINGS]:
        if not isinstance(item, Mapping):
            continue
        refs = [r for r in (item.get("action_refs") or [])
                if isinstance(r, int) and not isinstance(r, bool)] \
            if isinstance(item.get("action_refs"), list) else []
        severity = str(item.get("severity") or "warn").lower()
        findings.append({
            "title": _one_line(item.get("title"), 200) or "(untitled)",
            "severity": severity if severity in ("error", "warn", "info") else "warn",
            "evidence": plain(item.get("evidence"))[:MAX_TEXT],
            "suggestion": plain(item.get("suggestion"))[:MAX_TEXT],
            "action_refs": refs[:10],
            "code_fix_prompt": plain(item.get("code_fix_prompt"))[:MAX_TEXT],
        })
    actions = [a for a in list(data.get("actions") or [])[:MAX_ACTIONS]
               if isinstance(a, Mapping)] if isinstance(data.get("actions"), list) else []
    return {
        "subject": _one_line(data.get("subject"), 150),
        "headline": plain(data.get("headline"))[:MAX_TEXT],
        "all_clear": bool(data.get("all_clear")) and not findings,
        "findings": findings,
        "actions": actions,
    }


def validate_actions(conn: sqlite3.Connection, settings: Any,
                     proposed: list[Mapping[str, Any]]
                     ) -> tuple[list[dict[str, Any]], list[str]]:
    """(offered, "suggested but not offered" lines). Every proposal is checked
    against the catalogue AND against the database now; an invalid one is
    dropped with its reason, never offered."""
    offered: list[dict[str, Any]] = []
    dropped: list[str] = []
    numbers: set[int] = set()
    seen: set[tuple[str, str]] = set()
    for item in proposed:
        name = str(item.get("action") or "")
        n = item.get("n")
        label = f"{name or '(no action)'} {json.dumps(item.get('params') or {}, sort_keys=True)}"
        if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= 99):
            dropped.append(f"{label}: it has no usable number")
            continue
        if n in numbers:
            dropped.append(f"{label}: its number {n} was already used")
            continue
        clean, why = triage_actions.validate(conn, settings, name, item.get("params"))
        if clean is None:
            dropped.append(f"{label}: {why}")
            continue
        key = (name, triage_actions.params_json(clean))
        if key in seen:
            dropped.append(f"{label}: the same action is already offered")
            continue
        seen.add(key)
        numbers.add(n)
        offered.append({"n": n, "action": name, "params": clean,
                        "why": _one_line(item.get("why"), 400)})
    return offered, dropped


# --------------------------------------------------------------- the email

def _footer(conn: sqlite3.Connection, token: str, expires_at: str,
            reply_enabled: bool) -> list[str]:
    if not reply_enabled:
        return ["Replies are switched off on this server (Settings, Alerts, SERVER "
                "CHECK: reply address), so these can only be done on the dashboard."]
    return ['To carry any of these out, reply to this email, e.g. "do 1 and 3".',
            f"Reference: CCT-{token}   (valid until {local_time(conn, expires_at)}, "
            f"each action runs once)"]


def compose_report(
    conn: sqlite3.Connection, report: Mapping[str, Any],
    offered: list[Mapping[str, Any]], dropped: list[str], *,
    token: str, expires_at: str, reply_enabled: bool,
) -> tuple[str, str]:
    topic = report.get("subject") or ("all clear" if report.get("all_clear")
                                      else "what needs you")
    subject = _one_line(f"{SUBJECT_PREFIX}: {topic}", 200)
    lines: list[str] = []
    headline = report.get("headline") or (
        "All clear: nothing on the server or the fleet needs a person."
        if report.get("all_clear") else "")
    if headline:
        lines += [headline, ""]
    findings = list(report.get("findings") or [])
    if findings:
        lines += ["WHAT NEEDS YOU", ""]
        for i, f in enumerate(findings, 1):
            lines.append(f"{i}. [{str(f['severity']).upper()}] {f['title']}")
            if f.get("evidence"):
                lines.append(f"   Evidence: {f['evidence']}")
            if f.get("suggestion"):
                lines.append(f"   Suggested: {f['suggestion']}")
            refs = [r for r in f.get("action_refs") or []
                    if any(a["n"] == r for a in offered)]
            if refs:
                lines.append("   Actions: " + ", ".join(f"[{r}]" for r in refs))
            if f.get("code_fix_prompt"):
                lines.append("   A prompt for a code fix (paste into Claude Code in the repo):")
                lines += ["     " + ln for ln in str(f["code_fix_prompt"]).splitlines()]
            lines.append("")
    if offered:
        lines += ["ACTIONS A REPLY CAN CARRY OUT", ""]
        for a in offered:
            why = f" - {a['why']}" if a.get("why") else ""
            lines.append(f"[{a['n']}] {triage_actions.describe(a['action'], a['params'])}{why}")
        lines.append("")
    if dropped:
        lines += ["Suggested but not offered:"]
        lines += [f"- {plain(d)}" for d in dropped]
        lines.append("")
    if offered:
        lines += _footer(conn, token, expires_at, reply_enabled)
    else:
        lines.append("Nothing in this check can be done by reply.")
    return subject, plain("\n".join(lines)) + "\n"


def _fallback_summary(bundle: Mapping[str, Any]) -> list[str]:
    """What the dashboard can say WITHOUT the model: open notices' titles,
    the fleet grid's why-sentences, collector kinds not ok. Every section is
    optional; a section the bundle could not read says so."""
    lines: list[str] = []
    notices = bundle.get("open_notices")
    if isinstance(notices, list):
        lines.append(f"Open notices ({len(notices)}):")
        for n in notices[:40]:
            what = (db.NOTICE_KINDS.get(str(n.get("kind"))) or {}).get("what") or n.get("kind")
            lines.append(f"- [{str(n.get('severity') or '').upper()}] {what}: {n.get('subject') or ''}".rstrip(": "))
        if not notices:
            lines.append("- none")
    else:
        lines.append("Open notices: could not be read.")
    lines.append("")
    fleet = bundle.get("fleet")
    if isinstance(fleet, Mapping) and "error" not in fleet:
        rows = []
        for e in fleet.get("editors") or []:
            why = e.get("why") if isinstance(e, Mapping) else None
            if isinstance(why, Mapping) and why.get("sentence") and not why.get("informational"):
                rows.append(f"- {e.get('editor_username')}/{e.get('machine')}: {why['sentence']}")
        lines.append("Computers not syncing:" if rows else "Computers not syncing: none")
        lines += rows
    else:
        lines.append("The fleet grid could not be read.")
    lines.append("")
    collector = bundle.get("collector")
    if isinstance(collector, Mapping) and "error" not in collector:
        bad = [f"- {k}: {(v or {}).get('error') or 'failed'}"
               for k, v in sorted((collector.get("kinds") or {}).items())
               if isinstance(v, Mapping) and not v.get("ok")]
        lines.append("Background jobs failing:" if bad else "Background jobs failing: none")
        lines += bad
    else:
        lines.append("The background jobs' health could not be read.")
    return lines


def compose_fallback(reason: str, bundle: Mapping[str, Any]) -> tuple[str, str]:
    subject = f"{SUBJECT_PREFIX}: the analysis could not run"
    lines = [f"The server check could not run its analysis: {plain(reason)}", "",
             "What the dashboard itself can say:", ""]
    lines += _fallback_summary(bundle)
    lines += ["", "This message is sent because the check always reports. If these "
                  "stop arriving, the server check itself is broken."]
    return subject, plain("\n".join(lines)) + "\n"


# --------------------------------------------------------------- the ledger

def expire_actions(conn: sqlite3.Connection, now: str) -> int:
    cur = conn.execute(
        "UPDATE triage_actions SET state='expired' WHERE state='offered' AND run_id IN "
        "(SELECT id FROM triage_runs WHERE token_expires_at IS NOT NULL "
        " AND token_expires_at <= ?)", (now,))
    return int(cur.rowcount or 0)


def prune(conn: sqlite3.Connection, settings: Any, now: str) -> int:
    """Keep KEEP_DAYS of runs, their actions, the replies and the run
    directories. -> runs removed."""
    cutoff = (db.parse_iso(now) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    old = [int(r["id"]) for r in conn.execute(
        "SELECT id FROM triage_runs WHERE started_at < ?", (cutoff,))]
    for run_id in old:
        conn.execute("DELETE FROM triage_actions WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM triage_runs WHERE id=?", (run_id,))
        shutil.rmtree(_run_dir(settings, run_id), ignore_errors=True)
    conn.execute("DELETE FROM triage_replies WHERE received_at < ?", (cutoff,))
    return len(old)


def _finish(conn: sqlite3.Connection, run_id: int, now: str, status: str,
            report: Mapping[str, Any], email_ok: bool, detail: str) -> None:
    conn.execute(
        "UPDATE triage_runs SET finished_at=?, status=?, report_json=?, email_ok=?, "
        "detail=? WHERE id=?",
        (now, status, json.dumps(report, ensure_ascii=False), 1 if email_ok else 0,
         detail[:800], int(run_id)))


def _send(conn: sqlite3.Connection, settings: Any, subject: str, text: str,
          reply_to: str, now: str) -> dict[str, Any]:
    """The report through `alerts._transmit`, with the write lock released
    around the network call (alerts._send_committed's rule), and its ONE
    alert_log row: that row is what retires the slot."""
    conn.commit()
    outcome = alerts._transmit(conn, settings, subject, text, label="triage",
                               reply_to=reply_to)
    db.record_alert(conn, KIND_TRIAGE, LEDGER_SUBJECT, outcome["sent_to"],
                    outcome["ok"], outcome["detail"], now)
    conn.commit()
    return outcome


# ------------------------------------------------------------------ the run

def run(settings: Any, now: str | None = None, *, forced: bool = False) -> dict[str, Any]:
    """One check, start to finish, on its own connection. Never raises."""
    now = now or db.utcnow_iso()
    conn = db.connect(settings.db_path)
    run_id = 0
    status, detail, email_ok = "failed", "", False
    try:
        values = alerts.get_settings(conn)
        reply_to = (values.get("alerts_triage_reply_to") or "").strip()
        reply_enabled = triage_mail.replies_enabled(values)
        expire_actions(conn, now)
        prune(conn, settings, now)
        token = secrets.token_urlsafe(16)
        expires_at = _iso_plus(now, TOKEN_TTL_SECONDS)
        cur = conn.execute(
            "INSERT INTO triage_runs (started_at, status, token_hash, token_expires_at) "
            "VALUES (?, 'running', ?, ?)",
            (now, hashlib.sha256(token.encode("utf-8")).hexdigest(), expires_at))
        run_id = int(cur.lastrowid or 0)
        conn.commit()

        bundle = build_bundle(conn, settings, now)
        run_dir = _run_dir(settings, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "evidence.json").write_text(scrub(bundle), encoding="utf-8")

        report: dict[str, Any] = {}
        offered: list[dict[str, Any]] = []
        try:
            cli, why = cli_gate(conn, settings)
            if not cli:
                raise TriageError(why)
            package_dir = str(Path(__file__).resolve().parent)
            model_arg, _family = cards_ai.cli_model_arg(settings, TRIAGE_MODEL)
            stdout = run_cli(build_argv(cli, model_arg, package_dir),
                             render_prompt(package_dir), cwd=str(run_dir),
                             timeout=CLI_TIMEOUT_SECONDS, settings=settings)
            report = clean_report(parse_report(stdout))
            offered, dropped = validate_actions(conn, settings, report["actions"])
            subject, text = compose_report(conn, report, offered, dropped, token=token,
                                           expires_at=expires_at,
                                           reply_enabled=reply_enabled)
            status = "ok"
        except TriageError as exc:
            status, detail = "fallback", str(exc)
            offered = []
            subject, text = compose_fallback(detail, bundle)
        for a in offered:
            conn.execute(
                "INSERT INTO triage_actions (run_id, n, action, params_json, why, state) "
                "VALUES (?, ?, ?, ?, ?, 'offered')",
                (run_id, a["n"], a["action"], triage_actions.params_json(a["params"]),
                 a.get("why") or ""))
        outcome = _send(conn, settings, subject, text, reply_to, now)
        email_ok = bool(outcome["ok"])
        _finish(conn, run_id, db.utcnow_iso(), status,
                {"subject": subject, "body": text, "report": report, "forced": forced},
                email_ok, detail or str(outcome.get("detail") or ""))
        conn.commit()
    except Exception as exc:                                        # noqa: BLE001
        # ALWAYS SEND, even here: an absent email is the only sign of a dead
        # agent the owner is promised, so a crash must still be a message.
        log.exception("triage: the server check failed")
        detail = f"{type(exc).__name__}: {str(exc)[:200]}"
        try:
            conn.rollback()
            subject = f"{SUBJECT_PREFIX}: the check failed"
            text = (f"The server check failed before it could finish: {detail}\n\n"
                    f"Nothing was changed. The next check will try again.\n")
            outcome = _send(conn, settings, subject, text, "", now)
            email_ok = bool(outcome["ok"])
            if run_id:
                _finish(conn, run_id, db.utcnow_iso(), "failed",
                        {"subject": subject, "body": text, "forced": forced},
                        email_ok, detail)
                conn.commit()
        except Exception:                                           # noqa: BLE001
            log.exception("triage: could not even report the failure")
    finally:
        try:
            db.meta_delete(conn, META_RUNNING)
            conn.commit()
        except sqlite3.Error:
            pass
        conn.close()
    return {"run_id": run_id, "status": status, "email_ok": email_ok, "detail": detail}


# ----------------------------------------------------------- the machinery

_RUN_LOCK = threading.Lock()
_POLLER: threading.Thread | None = None
_POLLER_LOCK = threading.Lock()
_POLLER_STOP = threading.Event()


def _start_thread(target: Callable[..., Any], name: str, *args: Any) -> threading.Thread:
    """The one thread seam, so the suite never starts a real run."""
    thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    thread.start()
    return thread


def _run_thread(settings: Any, forced: bool) -> None:
    try:
        run(settings, forced=forced)
    finally:
        _RUN_LOCK.release()


def _running_since(conn: sqlite3.Connection, now: str) -> str:
    since = db.meta_get(conn, META_RUNNING) or ""
    if not since:
        return ""
    try:
        if db.age_seconds(since, now) >= RUN_STALE_SECONDS:
            return ""                    # a dead run's row does not block
    except (ValueError, TypeError):
        return ""
    return since


def _try_start(conn: sqlite3.Connection, settings: Any, now: str,
               forced: bool) -> tuple[bool, str]:
    if not _RUN_LOCK.acquire(blocking=False):
        return False, "a server check is already running"
    try:
        since = _running_since(conn, now)
        if since:
            _RUN_LOCK.release()
            return False, f"a server check has been running since {local_time(conn, since)}"
        db.meta_set(conn, META_RUNNING, now)
        conn.commit()
        _start_thread(_run_thread, "dash-triage-run", settings, forced)
    except Exception:
        if _RUN_LOCK.locked():
            _RUN_LOCK.release()
        raise
    return True, "started"


def _poll_loop(settings: Any) -> None:
    while True:
        try:
            if triage_mail.poll(settings).get("disabled"):
                return
        except Exception:                                           # noqa: BLE001
            log.exception("triage: the reply poll failed")
        if _POLLER_STOP.wait(POLL_SECONDS):
            return


def _ensure_poller(settings: Any, values: Mapping[str, str]) -> None:
    """The reply poller: one daemon thread, every POLL_SECONDS while replies
    are enabled. It ends itself when they are switched off, and the next
    alerts pass starts it again when they are switched back on."""
    global _POLLER
    if not triage_mail.replies_enabled(values):
        return
    with _POLLER_LOCK:
        if _POLLER is not None and _POLLER.is_alive():
            return
        _POLLER = _start_thread(_poll_loop, "dash-triage-replies", settings)


def maybe_start(settings: Any, now: str, conn: sqlite3.Connection | None = None
                ) -> dict[str, Any]:
    """Called by `alerts.run_cycle` after the heartbeat. Decides; never runs.

    Also stamps the check evidence for `triage_reply_refused` on every pass,
    because that kind is event-shaped (a refused reply is a thing that
    happened) and a registered kind nothing stamps renders [ NOT CHECKED ].
    """
    own = conn is None
    conn = conn if conn is not None else db.connect(settings.db_path)
    try:
        db.mark_notice_checked(conn, triage_mail.REFUSED_KIND, now)
        values = alerts.get_settings(conn)
        conn.commit()
        if (values.get("alerts_triage") or "0") != "1":
            return {"started": False, "why": "off"}
        _ensure_poller(settings, values)
        if not triage_due(conn, now):
            return {"started": False, "why": "not due"}
        started, why = _try_start(conn, settings, now, forced=False)
        return {"started": started, "why": why}
    finally:
        if own:
            conn.close()


def start_run(settings: Any, conn: sqlite3.Connection,
              now: str | None = None) -> tuple[bool, str]:
    """[ RUN NOW ]: a run regardless of the schedule, still one at a time,
    and still only with the check switched on and a channel to send it by."""
    now = now or db.utcnow_iso()
    values = alerts.get_settings(conn)
    if (values.get("alerts_triage") or "0") != "1":
        return False, "the server check is off. Turn it on and save first."
    if (values.get("alerts_sink") or alerts.SINK_NONE) == alerts.SINK_NONE:
        return False, "no alert channel is set up, so the report would go nowhere."
    return _try_start(conn, settings, now, forced=True)


# ------------------------------------------------------------- the page

def status_view(conn: sqlite3.Connection, settings: Any) -> dict[str, Any]:
    """What the SERVER CHECK block shows. Never raises: it is part of a page
    whose job is to show why alerts are not arriving."""
    try:
        values = alerts.get_settings(conn)
        cli, cli_why = cli_gate(conn, settings)
        row = conn.execute("SELECT * FROM triage_runs ORDER BY id DESC LIMIT 1").fetchone()
        last = None
        if row is not None:
            last = {"id": int(row["id"]), "started_at": local_time(conn, row["started_at"]),
                    "status": row["status"], "email_ok": bool(row["email_ok"]),
                    "detail": row["detail"] or ""}
        now = db.utcnow_iso()
        since = _running_since(conn, now)
        return {
            "enabled": (values.get("alerts_triage") or "0") == "1",
            "cli_ok": bool(cli), "cli_why": cli_why,
            "imap_host": triage_mail.imap_host(values),
            "replies_enabled": triage_mail.replies_enabled(values),
            "timezone": alerts.timezone_name(conn),
            "last_run": last,
            "running_since": local_time(conn, since) if since else "",
            "last_poll": db.meta_get_json(conn, triage_mail.META_POLL) or {},
        }
    except Exception as exc:                                        # noqa: BLE001
        log.exception("triage: the status block could not be built")
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def report_text(conn: sqlite3.Connection, run_id: int) -> str | None:
    row = conn.execute("SELECT * FROM triage_runs WHERE id=?", (int(run_id),)).fetchone()
    if row is None:
        return None
    try:
        report = json.loads(row["report_json"] or "{}")
    except ValueError:
        report = {}
    if not report.get("body"):
        return (f"Server check #{row['id']}, started {row['started_at']}: "
                f"{row['status']}. {row['detail'] or ''}\n")
    return f"Subject: {report.get('subject', '')}\n\n{report['body']}"
