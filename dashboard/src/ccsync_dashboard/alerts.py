"""The fleet's outbound voice, and its self-diagnosis.

SYS-8 (resilience sweep 2026-08-28). Every alarm this system raises -- a
tripped lane B breaker, a fleet halt, a folder with no filter, an editor 12 GB
behind -- has been PULL-ONLY. The sweep read the 4,821-line ledger as a
taxonomy and found that **0 of ~120 entries were discovered by the system
telling anybody**; every long outage (SYNC-17's 18 h, CR-27a's 18 h, CR-86's
two days) was found by the owner happening to open the page. The dashboard,
whose stated job is to tell everyone whether their footage is syncing, has
never once been the discoverer of an outage.

Nothing here MEASURES anything new. Every check is a reading of state four
other modules already compute (health.why_not_syncing, db.collector_health,
db.get_feed_state, db.fetch_audit), which is the point: the gap was never the
data, it was that the data sat behind a page nobody had open at 18:00 on a
Friday.

THE CHECKS ARE DATA (`ALERT_KINDS`), not a chain of ifs. One registry, one
`scan()` that evaluates all of them every collector cycle, and one delivery
path. Adding a check is adding a row; the dedup, the recovery message, the
page, the weekly report's "checked and found nothing wrong" list and the
`/api/v1/health` counts all pick it up with no second edit.

Every finding must read as a DIAGNOSIS a non-technical owner can act on: what
is wrong, on which computer, since when, why it matters in one sentence, and
the exact next action (a button on this dashboard, or a tray action for the
editor). The technical detail goes on a second line, never in the sentence.

A CHECK THAT CANNOT RUN BECOMES ITS OWN FINDING (`check_failed`). Silence from
a check that raised would be "could not check" rendered as "fine", which is
the whole mistake this module exists to end.

Delivery is a pluggable sink chosen by site settings: "none" (the default and
the vendor build's shape), "smtp", or "webhook" -- a POST of {subject, text}
to an https URL, which is how a Tailscale-reachable receiver is fed without
this container growing a single byte of new inbound surface. With the sink at
"none" the scan still runs and the Alerts page still shows what is open, so a
site that never configures a sink still gets the diagnosis.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shutil
import smtplib
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Mapping

from . import db, health

log = logging.getLogger("ccsync.dashboard.alerts")

SINK_NONE = "none"
SINK_SMTP = "smtp"
SINK_WEBHOOK = "webhook"
SINKS = (SINK_NONE, SINK_SMTP, SINK_WEBHOOK)

SEV_ERROR = "error"
SEV_WARN = "warn"

# The report is scheduled, not triggered, so it is not a kind in the registry.
KIND_WEEKLY = "weekly"
KIND_TEST = "test"

# The suffix a RECOVERED record is filed under. A separate kind namespace
# rather than a column, so "is this subject currently alerted" is one
# comparison of two timestamps and no migration.
RECOVERED_SUFFIX = ".ok"

# A machine that has not reported for this long is silent. The same 24 h the
# finding names, and deliberately far above health.STALE_EDITOR_RED_SECONDS
# (6 h): the grid may redden at six hours, but waking somebody by mail wants a
# threshold no laptop lid closed over lunch can reach.
SILENT_SECONDS = 24 * 3600

# Five minutes, not the grid's one minute: the chip is free and a mail is not.
CLOCK_SKEW_ALERT_SECONDS = 5 * 60
ENGINE_DOWN_SECONDS = 3600
LANE_ERROR_SECONDS = 3600
RED_UNEXPLAINED_SECONDS = 3600
RESTARTS_ALERT = 3
UPGRADE_FAILURES_ALERT = 8
FEED_STALE_DAYS = 7
KEY_DRAIN_DAYS = 7
VERSIONS_BEHIND_ALERT = 3
# The dashboard's OWN volume. Percentages only: /data on an appliance is a
# share of a pool nobody sized for this container, so an absolute floor would
# be wrong on both ends.
DATA_DISK_RED_PERCENT = 5.0
DATA_DISK_WARN_PERCENT = 10.0

WEEKLY_WEEKDAY = 0          # Monday, datetime.weekday()
WEEKLY_HOUR = 8             # 08:00 site-local

# Wall-clock ceiling on ONE delivery. The collector is a single thread running
# every due kind in series (ops-efficiency-5's lesson): an SMTP server that
# hangs rather than refuses must not park enforce, connections and provision
# behind it.
SEND_TIMEOUT_SECONDS = 20.0

MAX_SETTING_CHARS = 400
MAX_PASSWORD_CHARS = 400
MAX_BODY_CHARS = 60000
# One machine cannot fill a mail queue: a fleet where every check fires on
# every machine still sends a bounded number of messages per cycle.
MAX_FINDINGS_PER_KIND = 40

# The env var that overrides the stored SMTP password, on the same
# "ENV ALWAYS WINS" rule ai_providers.read_key applies to a customer's API
# keys: a deployment that already carries the secret in its compose file must
# keep working, and the page then says the value is the deployment's rather
# than pretending a Set button would take effect.
SMTP_PASSWORD_ENV = "DASH_ALERTS_SMTP_PASSWORD"


class AlertError(Exception):
    """A refusal a human reads. Never carries a secret: this string reaches a
    browser, a log and somebody's screenshot."""


# ------------------------------------------------------------- site settings
#
# Their own writer rather than site_store.KEYS, for the reason ai_providers
# gives: these are NOT manifest fields. `site_store.set_many` validates
# against its own key list and would (correctly) refuse them, and adding them
# there would publish an SMTP username to every installer in
# `GET /api/v1/site`.

SETTING_KEYS: dict[str, str] = {
    "alerts_sink": "sink",
    "alerts_smtp_host": "str",
    "alerts_smtp_port": "int",
    "alerts_smtp_user": "str",
    "alerts_smtp_from": "str",
    "alerts_smtp_to": "str",
    "alerts_smtp_tls": "bool",
    "alerts_webhook_url": "https",
    "alerts_timezone": "str",
    "alerts_weekly": "bool",
}

_DEFAULTS = {
    "alerts_sink": SINK_NONE,
    "alerts_smtp_port": "587",
    "alerts_smtp_tls": "1",
    "alerts_weekly": "1",
}


def _validate(key: str, raw: str) -> str:
    kind = SETTING_KEYS.get(key)
    if kind is None:
        raise AlertError(f"{key!r} is not an alert setting")
    value = str(raw or "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise AlertError(f"{key}: must not contain control characters")
    if len(value) > MAX_SETTING_CHARS:
        raise AlertError(f"{key}: must be at most {MAX_SETTING_CHARS} characters")
    if kind == "sink":
        if value not in SINKS:
            raise AlertError(f"alerts_sink must be one of {', '.join(SINKS)}")
        return value
    if kind == "int":
        if not value:
            return ""
        if not value.isdigit() or not (0 < int(value) < 65536):
            raise AlertError(f"{key}: must be a port number between 1 and 65535")
        return str(int(value))
    if kind == "bool":
        if value in ("1", "0", ""):
            return value or "0"
        raise AlertError(f"{key}: must be '1' or '0'")
    if kind == "https":
        # https ONLY, and refused at the moment it is typed rather than at
        # 03:00 on a Sunday when the first alert goes out in the clear. A
        # webhook body carries machine names, editor names and the reason the
        # fleet is broken.
        if value and not value.lower().startswith("https://"):
            raise AlertError("the webhook URL must start with https:// "
                             "(an alert body names your editors and machines)")
        return value
    if key == "alerts_timezone" and value:
        _zone(value)                       # raises AlertError on a bad name
    return value


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    """Every alert setting, defaults filled in. A MISSING TABLE IS DEFAULTS,
    not an error (ai_providers.get_setting's rule): this is read from the
    collector thread, which can run against a database whose migrations have
    not finished, and the honest answer there is "this site has not said"."""
    stored: dict[str, str] = {}
    try:
        rows = conn.execute(
            "SELECT key, value FROM site_settings WHERE key LIKE 'alerts_%'"
        ).fetchall()
        stored = {str(r["key"]): str(r["value"]) for r in rows}
    except sqlite3.Error:
        stored = {}
    return {key: stored.get(key, _DEFAULTS.get(key, "")) for key in SETTING_KEYS}


def set_settings(
    conn: sqlite3.Connection, values: Mapping[str, str], updated_by: str,
) -> dict[str, str]:
    """Validate EVERY field first, then write them all: a form with one bad
    port must change nothing rather than half-applying (site_store.set_many's
    rule). Unknown keys are refused, not ignored."""
    normalised = {key: _validate(key, raw) for key, raw in values.items()}
    now = db.utcnow_iso()
    for key, value in normalised.items():
        conn.execute(
            "INSERT INTO site_settings (key, value, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (key, value, now, str(updated_by or "?")),
        )
    return normalised


# ------------------------------------------------------------ the password
#
# In a FILE under <data>/secrets/, never in site_settings: a database backup
# must not be a working credential (db.py SCHEMA_V15's rule, the same one that
# keeps editor report tokens and the AI keys out of this table).

def password_path(settings: Any) -> Path:
    return Path(settings.db_path).parent / "secrets" / "alerts" / "smtp_password"


def read_password(settings: Any, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(value, source) where source is "env" | "file" | "". ENV WINS."""
    env = os.environ if env is None else env
    from_env = (env.get(SMTP_PASSWORD_ENV, "") or "").strip()
    if from_env:
        return from_env, "env"
    try:
        stored = password_path(settings).read_text(encoding="utf-8").strip()
    except OSError:
        stored = ""
    return (stored, "file") if stored else ("", "")


def set_password(settings: Any, raw: str) -> str:
    """Store the SMTP password 0600 and return its MASK.

    Never echoes the value back, not even in a refusal: an error message that
    quotes the secret puts it in the browser console, the container log and
    any screenshot of the page.
    """
    from . import secrets_boot

    value = str(raw or "").strip()
    if not value:
        raise AlertError("the password is blank")
    if len(value) > MAX_PASSWORD_CHARS:
        raise AlertError(f"that password is longer than {MAX_PASSWORD_CHARS} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise AlertError("the password contains control characters, paste it again")
    path = password_path(settings)
    try:
        secrets_boot.write_secret_file(path, value)
    except OSError as exc:
        raise AlertError(
            f"could not write the password to {path.parent} "
            f"({exc.strerror or exc}). That directory must be writable by the "
            f"container's uid."
        ) from None
    log.info("alerts: SMTP password stored")
    return mask(value)


def clear_password(settings: Any) -> bool:
    try:
        password_path(settings).unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AlertError(f"could not remove the stored password ({exc.strerror or exc})")
    log.info("alerts: SMTP password cleared")
    return True


def mask(value: str) -> str:
    """A short value is masked ENTIRELY. ai_providers.mask's twin, and its
    rule: four characters of a six-character secret is the secret."""
    value = str(value or "")
    if not value:
        return ""
    if len(value) < 12:
        return "…"
    return f"{value[:3]}…{value[-4:]}"


def settings_view(conn: sqlite3.Connection, settings: Any) -> dict[str, Any]:
    """What the page and the API may see. THE PASSWORD IS NEVER IN HERE, only
    whether one is set and where it came from."""
    values = get_settings(conn)
    secret, source = read_password(settings)
    return {
        **values,
        "sinks": list(SINKS),
        "password_set": bool(secret),
        "password_source": source,
        "password_mask": mask(secret),
        "timezone": timezone_name(conn),
    }


# ----------------------------------------------------------------- the clock

def _iso_minus(now: str, seconds: float) -> str:
    return (db.parse_iso(now) - dt.timedelta(seconds=seconds)).isoformat()


def _age(stamp: Any, now: str) -> float | None:
    """Seconds since `stamp`, or None when it cannot be read. None is "we do
    not know", and every caller treats it as "do not claim a duration"."""
    if not stamp:
        return None
    try:
        return db.age_seconds(str(stamp), now)
    except (ValueError, TypeError):
        return None


def _zone(name: str):
    """A ZoneInfo, or AlertError naming the bad value. Refused at the moment
    an admin types it rather than at 08:00 on the Monday it silently sends
    nothing."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise AlertError(f"{name!r} is not a time zone this server knows "
                         f"(use an IANA name such as Europe/London)") from None


def timezone_name(conn: sqlite3.Connection) -> str:
    """This site's zone, or "UTC". The alerts setting first, then a plain
    `timezone` row if some other part of the product ever grows one, then
    UTC, which is what every timestamp in this database already is."""
    values = get_settings(conn)
    name = (values.get("alerts_timezone") or "").strip()
    if not name:
        try:
            row = conn.execute(
                "SELECT value FROM site_settings WHERE key='timezone'").fetchone()
            name = "" if row is None else str(row["value"]).strip()
        except sqlite3.Error:
            name = ""
    return name or "UTC"


def _zone_or_utc(conn: sqlite3.Connection):
    name = timezone_name(conn)
    try:
        return _zone(name), name
    except AlertError:
        # NAMED, not swallowed: a zone this container cannot resolve (a slim
        # image with no tzdata) would otherwise move the weekly report by
        # hours with nothing anywhere saying why.
        log.warning("alerts: time zone %r is not available in this container; "
                    "using UTC for the weekly schedule", name)
        return dt.timezone.utc, "UTC"


def previous_weekly_slot(now: dt.datetime, zone) -> dt.datetime:
    """The most recent Monday 08:00 IN `zone` at or before `now`, as an
    aware UTC datetime.

    Computed from the local calendar rather than by counting hours, because a
    fleet on Europe/London crossing a DST boundary would otherwise get its
    report at 07:00 for half the year and skip or double one week at the
    change.
    """
    local = now.astimezone(zone)
    slot = local.replace(hour=WEEKLY_HOUR, minute=0, second=0, microsecond=0)
    slot -= dt.timedelta(days=(slot.weekday() - WEEKLY_WEEKDAY) % 7)
    if slot > local:
        slot -= dt.timedelta(days=7)
    return slot.astimezone(dt.timezone.utc)


def weekly_due(conn: sqlite3.Connection, now: str) -> bool:
    """Whether this week's report is owed.

    "Owed" is DURABLE and not a timer: the last weekly send is compared
    against the most recent Monday-08:00 slot, so a container replaced at
    07:59 on Monday sends it once, a container down for the whole of Monday
    still sends it on Tuesday, and one restarted six times on Monday afternoon
    does not send it six times.
    """
    if (get_settings(conn).get("alerts_weekly") or "0") != "1":
        return False
    zone, _name = _zone_or_utc(conn)
    try:
        now_dt = db.parse_iso(now)
    except (ValueError, TypeError):
        return False
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=dt.timezone.utc)
    slot = previous_weekly_slot(now_dt, zone)
    last = db.last_alert_at(conn, KIND_WEEKLY, ok_only=False)
    if not last:
        return True
    try:
        last_dt = db.parse_iso(last)
    except (ValueError, TypeError):
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=dt.timezone.utc)
    return last_dt < slot


# ---------------------------------------------------------------- the phrasing

def _age_words(stamp: Any, now: str) -> str:
    seconds = _age(stamp, now)
    if seconds is None:
        return "never" if not stamp else str(stamp)
    if seconds < 0:
        return "in the future (check that computer's clock)"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"


def _duration_words(seconds: Any) -> str:
    try:
        total = int(abs(float(seconds)))
    except (TypeError, ValueError):
        return "an unknown time"
    if total < 90:
        return f"{total} seconds"
    if total < 5400:
        return f"{total // 60} minutes"
    if total < 48 * 3600:
        return f"{total // 3600} hours"
    return f"{total // 86400} days"


def _bytes_words(n: Any) -> str:
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "an unknown amount"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "an unknown amount"


def _who(entry: Mapping[str, Any]) -> str:
    return f"{entry.get('editor_username')}/{entry.get('machine')}"


def _lane_words(entry: Mapping[str, Any]) -> str:
    lanes = [l for l in (entry.get("lanes") or []) if isinstance(l, Mapping)]
    if not lanes:
        return "no lane ever reported"
    return ", ".join(f"{l.get('label') or l.get('lane')}={l.get('state')}" for l in lanes)


# ------------------------------------------------------------- the registry

Finding = dict            # {"subject", "diagnosis", "fix", "detail"}


def _f(subject: str, diagnosis: str, fix: str, detail: str = "") -> Finding:
    return {"subject": subject, "diagnosis": diagnosis, "fix": fix, "detail": detail}


@dataclass(frozen=True)
class AlertKind:
    """One thing this server checks, every cycle.

    `severity` decides the repeat rule, not just the colour: an "error"
    re-alerts once a day for as long as it is still true (an outage nobody
    acted on must not go quiet), a "warn" is said once and not again until it
    has cleared and come back.

    `what` is the line the weekly report prints in its "checked and found
    nothing wrong" list, so silence is provably CHECKED rather than
    unchecked.
    """
    kind: str
    severity: str
    title: str
    what: str
    check: Callable[["Ctx"], list[Finding]]


class Ctx:
    """Everything the checks read, gathered ONCE per scan.

    A check may not go back to the database for a per-machine query: this runs
    on the collector's single thread beside enforce and completion, and a scan
    that costs one query per machine per kind is a scan that gets turned off.
    Anything that could not be read is None or empty AND is itself reported by
    the `check_failed` kind rather than passing as "nothing wrong".
    """

    def __init__(self, conn: sqlite3.Connection, settings: Any, now: str) -> None:
        from .api import build_editors_view

        self.conn = conn
        self.settings = settings
        self.now = now
        self.fleet = build_editors_view(conn, now)
        self.editors: list[dict[str, Any]] = list(self.fleet.get("editors") or [])
        self.collector = db.collector_health(conn, now=now)
        self.feed = db.get_feed_state(conn)
        self.feed_mismatch = db.get_feed_runtime_mismatch(conn)
        self.halt = db.get_fleet_halt(conn, now)
        self.retracted = db.retracted_packages(conn, kind="companion")
        self.retired_keys = db.retired_key_identities(conn)
        # Machines a more specific kind has already named, so the catch-all
        # ("red for an hour and we cannot say why") does not repeat them.
        self.named: set[str] = set()

    def guard(self, entry: Mapping[str, Any]) -> Mapping[str, Any]:
        return entry.get("guard") or {}

    def name(self, subject: str) -> str:
        self.named.add(subject)
        return subject


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[Any]:
    """A defensive read of a table another work package owns.

    The notices ledger (v37) and the file-move state machine (v36) landed in
    the same wave as this module. A scan that raises because one table is not
    there yet is a scan that stops answering for the twenty checks that were
    ready, so a missing table reads as "nothing to report" HERE and is
    reported by the notices/file-move checks' own absence, never as a fault.
    """
    try:
        return list(conn.execute(sql, params))
    except sqlite3.Error:
        return []


# --------------------------------------------------------------- the checks
#
# Each returns a list of findings. Each finding's `diagnosis` is one or two
# plain sentences a non-technical owner can act on; `fix` names the exact next
# action; `detail` carries the technical half for whoever wants it.

def _check_breaker(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        if not g.get("breaker_tripped"):
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"Proxy download has stopped itself on {who}, "
            f"{_age_words(g.get('breaker_at'), ctx.now)}. Until somebody clears "
            f"it, that computer gets no new proxies, so the editor cannot see "
            f"anyone else's footage. Uploads from it are still running and "
            f"nothing has been deleted.",
            "On the dashboard: FLEET, then [ RESUME ] on that computer's row. "
            "Check the server looks right first: the brake exists because the "
            "NAS stopped looking like the tree.",
            str(g.get("breaker_reason") or "")))
    return out


def _check_fleet_halt(ctx: Ctx) -> list[Finding]:
    halt = ctx.halt
    if not halt.get("active") or halt.get("expired"):
        return []
    return [_f(
        "the whole fleet",
        f"Syncing is halted for every computer in the fleet. Nothing is going "
        f"up and nothing is coming down anywhere. It was set "
        f"{_age_words(halt.get('set_at'), ctx.now)} by "
        f"{halt.get('set_by') or 'an admin'}.",
        "On the dashboard: FLEET, then [ RELEASE THE HALT ] when whatever it "
        "was set for is over.",
        str(halt.get("reason") or ""))]


def _check_fleet_halt_expired(ctx: Ctx) -> list[Finding]:
    halt = ctx.halt
    if not (halt.get("active") and halt.get("expired")):
        return []
    return [_f(
        "the whole fleet",
        f"The fleet halt set {_age_words(halt.get('set_at'), ctx.now)} has run "
        f"past its own expiry time, so syncing has started again on its own. "
        f"If the reason it was set is still true, nobody has been told.",
        "On the dashboard: FLEET, and either set the halt again or confirm it "
        "is no longer needed.",
        f"expires_at={halt.get('expires_at')}")]


def _check_disk_park(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        if str(g.get("blocked_reason") or "") != "disk_full":
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} has parked its proxy download because the drive is nearly "
            f"full ({_bytes_words(g.get('disk_root_free_bytes'))} free). That "
            f"editor will not see anybody else's new footage until there is "
            f"room.",
            "Ask the editor to clear space on the sync drive, or untick a "
            "project for that computer on its project page.",
            str(g.get("blocked_detail") or "")))
    return out


def _check_disk_low(ctx: Ctx) -> list[Finding]:
    """The DISK chip's own RED, not a second threshold to reconcile (SYS-5).
    A machine that has never reported a disk section gets nothing, never a
    reassuring green: "could not check" is not "fine"."""
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        colour, percent = health.disk_status(g.get("disk_root_free_bytes"),
                                             g.get("disk_root_total_bytes"))
        if colour != health.RED or percent is None:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} has {_bytes_words(g.get('disk_root_free_bytes'))} free on "
            f"its sync drive ({percent:.0f} percent). Proxy download fills a "
            f"drive file by file, and the recoverable-files bin cannot be "
            f"cleared while the brake is on, so this ends with that editor "
            f"unable to work.",
            "Ask that editor to clear space on the sync drive, or untick a "
            "project for that computer on its project page.",
            f"measured {_age_words(g.get('disk_at'), ctx.now)}"))
    return out


def _check_silent(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        age = _age(e.get("received_at"), ctx.now)
        if e.get("received_at") and (age is None or age < SILENT_SECONDS):
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} has not been in touch since "
            f"{_age_words(e.get('received_at'), ctx.now)}. Everything this "
            f"dashboard shows for that computer is frozen at that moment, so a "
            f"green row there means nothing right now.",
            "Ask that editor to check the CC Sync tray icon is running and "
            "that the computer is on and online.",
            f"last known state: {_lane_words(e)}"))
    return out


def _check_report_refused(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        if not g.get("report_refused_at"):
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} IS running and IS trying to report, and this server is "
            f"turning it away ({_age_words(g.get('report_refused_at'), ctx.now)}). "
            f"That looks exactly like a computer that has been switched off, so "
            f"nothing below it on the fleet page is current.",
            "Ask that editor to click Sign in on the CC Sync tray on that "
            "computer.",
            str(g.get("report_refused_reason") or "")))
    return out


def _check_clock_skew(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        skew = g.get("clock_skew_seconds")
        try:
            if skew is None or abs(float(skew)) < CLOCK_SKEW_ALERT_SECONDS:
                continue
        except (TypeError, ValueError):
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who}'s clock is {_duration_words(skew)} out from the server's. "
            f"Proxy download only takes files past a minimum age, so a clock "
            f"this far out makes it transfer nothing at all while reporting no "
            f"error: a perfectly green row that is downloading nothing.",
            "On that computer, turn on Set time automatically in the operating "
            "system's date and time settings.",
            f"clock_skew_seconds={skew}"))
    return out


def _check_engine_down(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        age = _age(g.get("supervisor_down_since"), ctx.now)
        if age is None or age < ENGINE_DOWN_SECONDS:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"The sync engine on {who} has been down for "
            f"{_duration_words(age)}. Project files and folders shared with "
            f"that computer are not moving in either direction.",
            "Ask that editor to quit and restart CC Sync from the tray. If it "
            "comes back down, send us their diagnostics.",
            f"{g.get('supervisor_attempts') or 0} automatic restart attempt(s) "
            f"failed. {g.get('supervisor_last_error') or ''}"))
    return out


def _check_nas_engine(ctx: Ctx) -> list[Finding]:
    if ctx.collector.get("syncthing_reachable") is not False:
        return []
    return [_f(
        "the server",
        "This server cannot reach its own sync engine. Project files and "
        "shared folders are not moving between the server and anybody, and no "
        "new project can be shared out.",
        "On the NAS: check the Syncthing app is running, then reload the "
        "dashboard's Settings page.",
        "collector: syncthing_reachable=false")]


def _check_lane_stalled(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        stalled = g.get("stalled_lane") or g.get("stalled_seconds")
        reason = (e.get("why") or {}).get("reason")
        if not stalled and reason != "lane_stalled":
            continue
        who = ctx.name(_who(e))
        sentence = (e.get("why") or {}).get("sentence") or (
            f"A sync lane on {who} is busy and nothing is moving")
        out.append(_f(
            who,
            f"{sentence}. A drive that has stopped answering reads exactly "
            f"like this, and the other lanes on that computer wait behind it.",
            "Ask that editor to restart CC Sync from the tray, and to check "
            "the sync drive opens in Explorer or Finder.",
            f"lane={g.get('stalled_lane')} seconds={g.get('stalled_seconds')} "
            f"killed={g.get('stalled_killed')}"))
    return out


def _check_lane_error(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        for lane in e.get("lanes") or []:
            if not isinstance(lane, Mapping) or str(lane.get("state")) != "error":
                continue
            age = _age(lane.get("state_since") or lane.get("received_at"), ctx.now)
            if age is None or age < LANE_ERROR_SECONDS:
                continue
            who = _who(e)
            ctx.name(who)
            label = lane.get("label") or lane.get("lane")
            out.append(_f(
                f"{who} {label}",
                f"{label} on {who} has been failing for "
                f"{_duration_words(age)}. Whatever that lane carries is not "
                f"moving for that editor.",
                "Open the computer's row on the FLEET page and read the error, "
                "then ask that editor to restart CC Sync from the tray.",
                str(lane.get("last_error") or "")))
    return out


def _check_folders_unfiltered(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        count = g.get("folders_unfiltered")
        if not count:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{count} shared folder(s) on {who} have no ignore filter written "
            f"yet. Without it, that computer will carry camera originals in "
            f"both directions over the internet instead of proxies only.",
            "It normally writes itself on the next sync turn. If it is still "
            "here tomorrow, ask that editor to restart CC Sync from the tray.",
            str(g.get("folders_unfiltered_names") or "")))
    return out


def _check_restarts(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        count = int(g.get("restarts_count_24h") or 0)
        if count < RESTARTS_ALERT:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"CC Sync on {who} has had to restart its own background work "
            f"{count} times in the last day. It is putting itself back "
            f"together each time, so the row looks fine, but something on that "
            f"computer keeps knocking it over.",
            "Ask that editor for Copy diagnostics from the CC Sync tray and "
            "send it to us.",
            f"last {g.get('restarts_last_at')}: {g.get('restarts_last_error') or ''}"))
    return out


def _check_crashes(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        if not g.get("crash_count"):
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{g['crash_count']} background task(s) on {who} have crashed and "
            f"written a report. The tray stays up and the lanes look normal, "
            f"which is why nobody notices.",
            "Ask that editor for Copy diagnostics from the CC Sync tray.",
            f"newest: {g.get('crash_newest') or '?'}"))
    return out


def _check_upgrade_failed(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        attempts = int(g.get("upgrade_attempts") or 0)
        if attempts < UPGRADE_FAILURES_ALERT:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} has tried and failed to install "
            f"{g.get('upgrade_version') or 'an update'} {attempts} times. It "
            f"is downloading the same file every few minutes and getting "
            f"nowhere, and the update will never arrive on its own. Antivirus "
            f"quarantine, a full disk and a proxy mangling the download all "
            f"look like this.",
            "Read the error on that computer's row on the FLEET page, then "
            "install the build by hand from the dashboard's INSTALLER link.",
            str(g.get("upgrade_last_error") or "")))
    return out


def _check_upgrade_reverted(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        if not g.get("upgrade_reverted_from"):
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} installed {g['upgrade_reverted_from']}, could not start it, "
            f"and put itself back on "
            f"{e.get('companion_version') or 'its old build'}. That build "
            f"should not be handed to anybody else.",
            "On the dashboard: SETTINGS, PACKAGES, and recall that build "
            "before making it current.",
            f"reverted_from={g.get('upgrade_reverted_from')}"))
    return out


def _check_collector_kinds(ctx: Ctx) -> list[Finding]:
    out = []
    for kind in ctx.collector.get("kinds") or []:
        if kind.get("status") != "red":
            continue
        out.append(_f(
            f"poll {kind.get('kind')}",
            f"The server's own background job '{kind.get('kind')}' last ran and "
            f"failed ({_age_words(kind.get('finished_at'), ctx.now)}). While it "
            f"is failing, the part of the fleet picture it produces is stale "
            f"and nothing on the page says so.",
            "On the dashboard: SETTINGS, and read the collector health panel "
            "at the bottom of the home page.",
            str(kind.get("note") or "")))
    return out


def _check_collector_stale(ctx: Ctx) -> list[Finding]:
    if not ctx.collector.get("collector_stale"):
        return []
    return [_f(
        "the server",
        "The server's background collector has not completed a cycle "
        "recently. While it is stopped, nothing shares a newly ticked "
        "project, nothing tidies the database, and every number on the fleet "
        "page ages quietly without changing colour.",
        "Restart the ccsync container on the NAS. If it comes back stale, "
        "send us the container log.",
        "collector_stale=true")]


def _check_watchdog(ctx: Ctx) -> list[Finding]:
    """Filled in by run_cycle, which is the only caller that knows.

    A watchdog restart is an EVENT, not a state: by the time anything could
    read it from the database it has already been recovered from. The kind is
    in the registry anyway so it appears in the weekly report's checked list
    and on the Alerts page.
    """
    return []


def _collector_alarm(ctx: Ctx, key: str, subject: str, diagnosis: str,
                     fix: str) -> list[Finding]:
    alarm = ctx.collector.get(key)
    if not alarm:
        return []
    return [_f(subject, diagnosis, fix, json.dumps(alarm, sort_keys=True)[:400])]


def _check_enforce_refusal(ctx: Ctx) -> list[Finding]:
    return _collector_alarm(
        ctx, "enforce_refusal", "sharing brake",
        "The server refused to apply a sharing change because it would have "
        "removed folders from more computers than it is allowed to in one go. "
        "Until this is cleared, ticks and unticks are not reaching the fleet.",
        "On the dashboard home page, read the brake banner and confirm the "
        "plan is what you meant before releasing it.")


def _check_deactivation_refusal(ctx: Ctx) -> list[Finding]:
    return _collector_alarm(
        ctx, "deactivation_refusal", "project deactivation brake",
        "The server refused to deactivate projects because too many "
        "disappeared from the tree at once. That is what a NAS share that "
        "failed to mount looks like, and applying it would have unshared real "
        "projects from every editor.",
        "Check the project tree is mounted on the NAS, then release the brake "
        "from the dashboard home page.")


def _check_enforce_plan(ctx: Ctx) -> list[Finding]:
    return _collector_alarm(
        ctx, "enforce_plan", "sharing plan held",
        "The server has a sharing change it has worked out but not applied.",
        "Open the dashboard home page and read the plan banner.")


def _check_ignored_sections(ctx: Ctx) -> list[Finding]:
    record = ctx.fleet.get("ignored_report_sections")
    if not record:
        return []
    names = sorted((record.get("sections") or {}).keys())
    if not names:
        return []
    return [_f(
        "report sections nobody reads",
        f"Editors' computers are sending {len(names)} piece(s) of information "
        f"this dashboard does not understand and is throwing away. That is how "
        f"three earlier faults stayed invisible for weeks: the computer was "
        f"saying what was wrong and nothing here was listening.",
        "This dashboard needs updating. Send us this list.",
        ", ".join(names))]


def _check_feed_stale(ctx: Ctx) -> list[Finding]:
    feed = ctx.feed or {}
    last = feed.get("last_checked_at")
    age = _age(last, ctx.now)
    if last and (age is None or age < FEED_STALE_DAYS * 86400):
        if not feed.get("last_error"):
            return []
    return [_f(
        "the update feed",
        f"This dashboard has not been able to check for new CC Sync builds "
        f"since {_age_words(last, ctx.now)}. Nobody in the fleet will be "
        f"offered a fix that has been released since then.",
        "Check the NAS can reach the internet, then press [ CHECK NOW ] on "
        "SETTINGS, PACKAGES.",
        str(feed.get("last_error") or ""))]


def _check_feed_runtime_mismatch(ctx: Ctx) -> list[Finding]:
    mismatch = ctx.feed_mismatch
    if not mismatch:
        return []
    return [_f(
        "the update feed",
        "Every new CC Sync build on offer needs a newer container than this "
        "NAS is running, so none of them can install themselves. Updates will "
        "keep appearing and never apply.",
        f"On the NAS: {mismatch.get('nas_hint') or 'use your NAS app manager to update the ccsync container'}.",
        "versions: " + ", ".join(mismatch.get("versions") or []))]


def _check_data_disk(ctx: Ctx) -> list[Finding]:
    settings = ctx.settings
    if settings is None:
        return []
    path = Path(getattr(settings, "db_path", "") or ".").parent
    try:
        usage = shutil.disk_usage(str(path))
    except OSError as exc:
        raise AlertError(f"could not read free space on {path} ({exc})") from None
    percent = 100.0 * usage.free / usage.total if usage.total else 100.0
    if percent >= DATA_DISK_WARN_PERCENT:
        return []
    return [_f(
        "the server's own storage",
        f"The volume this dashboard stores everything on has "
        f"{_bytes_words(usage.free)} free ({percent:.0f} percent). When it "
        f"fills, this dashboard stops recording anything: no fleet status, no "
        f"installers, no search index.",
        "Free space on the NAS volume that holds the ccsync data folder.",
        f"{usage.free} of {usage.total} bytes free at {path}")]


def _check_nas_tree(ctx: Ctx) -> list[Finding]:
    """The tree-unmounted canary.

    A share that failed to mount presents as an EMPTY directory, not as an
    error, and that empty directory is what once made the deactivation pass
    want to unshare every project on the fleet. Checked here as a standing
    line rather than only inside the pass that would act on it.
    """
    settings = ctx.settings
    projects_dir = str(getattr(settings, "projects_dir", "") or "")
    if not projects_dir:
        return []
    path = Path(projects_dir)
    try:
        if not path.exists():
            state = "is not there at all"
        elif not any(path.iterdir()):
            state = "is there but completely empty"
        else:
            return []
    except OSError as exc:
        raise AlertError(f"could not read {path} ({exc})") from None
    return [_f(
        "the project tree",
        f"The project tree this dashboard reads {state} ({projects_dir}). That "
        f"is what a NAS share that failed to mount looks like, and every "
        f"project on the fleet page is about to look deleted.",
        "On the NAS: check the dataset holding the project tree is mounted and "
        "that the ccsync container still has it.",
        f"path={projects_dir}")]


def _check_notices(ctx: Ctx) -> list[Finding]:
    """Open notices of severity error (UX-10's v37 table).

    Read defensively: the notices work package and this one landed in the same
    wave. An absent table is "this build has no notices ledger", not a fault.
    """
    rows = _rows(ctx.conn,
                 "SELECT kind, severity, subject, body, fix, first_seen FROM notices "
                 "WHERE cleared_at IS NULL AND severity='error' "
                 "ORDER BY last_seen DESC LIMIT 40")
    return [_f(
        f"{r['kind']}: {r['subject']}",
        f"{(r['body'] or r['subject'] or '').strip()} "
        f"(first seen {_age_words(r['first_seen'], ctx.now)})",
        (r["fix"] or "").strip() or "Open the dashboard home page and read "
                                    "PROBLEMS THE SERVER FOUND.",
        f"notice kind={r['kind']}") for r in rows]


def _check_out_of_tree(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        count = g.get("resolve_out_of_tree")
        if not count:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"The project open on {who} uses {count} clip(s) that are not in "
            f"the sync tree. Those clips will never upload and nobody else on "
            f"the fleet will ever see them, and the timeline will open with "
            f"red media on any other computer.",
            "Ask that editor to copy those clips into the project's own folder "
            "on the sync drive and relink them in Resolve.",
            f"bad prefix={g.get('resolve_bad_prefix')} missing={g.get('resolve_missing')} "
            f"scanned {_age_words(g.get('resolve_last_scan_at'), ctx.now)}"))
    return out


def _check_stray_projects(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        count = g.get("stray_projects_count")
        if not count:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} has {count} project folder(s) sitting outside the tree, "
            f"holding {_bytes_words(g.get('stray_projects_bytes'))}. Nothing "
            f"in there is backed up to the server or visible to anybody else.",
            "Ask that editor to move those folders into the sync tree, or "
            "confirm they are scratch and can be deleted.",
            f"stray_projects_bytes={g.get('stray_projects_bytes')}"))
    return out


def _check_moved_project_dirs(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        count = g.get("moved_project_dirs_count")
        if not count:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{count} project folder(s) on {who} are not where the tree says "
            f"they should be. Syncing for those projects will look busy and "
            f"move nothing, and files moved by hand come back.",
            "Move the folder back, or use [ MOVE ON THE SERVER AND ON EVERY "
            "MACHINE ] on the project page so every computer follows.",
            f"moved_project_dirs_count={count}"))
    return out


def _check_ingest_staging(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        staged = g.get("ingest_staging_bytes")
        if not staged:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{_bytes_words(staged)} of footage is sitting in the drop folder "
            f"on {who} and has not been filed into a project yet. It is on one "
            f"computer only.",
            "Ask that editor to finish the drop in CC Sync, or to file those "
            "clips into a project.",
            f"ingest_staging_bytes={staged}"))
    return out


def _check_file_moves(ctx: Ctx) -> list[Finding]:
    """File moves a computer was told about and never confirmed (v36).

    Defensive for the same reason `_check_notices` is: the file-move work
    package is this wave's, and its columns may not exist yet.
    """
    rows = _rows(ctx.conn,
                 "SELECT machine, rel_path, expired_at FROM file_move_targets "
                 "WHERE expired_at IS NOT NULL AND expired_at != '' LIMIT 40")
    return [_f(
        f"{r['machine']} {r['rel_path']}",
        f"A file this server moved was never confirmed as moved on "
        f"{r['machine']}, and the request has now aged out "
        f"({_age_words(r['expired_at'], ctx.now)}). That computer still holds "
        f"the file at the old path, so it will re-upload it and the move will "
        f"undo itself.",
        "Open the project page and use [ MOVE ON THE SERVER AND ON EVERY "
        "MACHINE ] again once that computer is back online.",
        f"expired_at={r['expired_at']}") for r in rows]


def _check_versions_behind(ctx: Ctx) -> list[Finding]:
    """A computer several releases behind the current build.

    Counts PUBLISHED builds newer than the one running, not a version-number
    difference: what matters is how many fixes that machine has not taken.
    """
    published: dict[str, list[tuple]] = {}
    for r in _rows(ctx.conn,
                   "SELECT platform, version FROM companion_packages "
                   "WHERE kind='companion' AND (retracted_at IS NULL OR retracted_at='')"):
        published.setdefault(str(r["platform"]), []).append(db.version_tuple(r["version"]))
    out = []
    for e in ctx.editors:
        version = db.version_tuple(e.get("companion_version"))
        if not version:
            continue
        newer = [v for v in published.get(e.get("platform") or "", []) if v > version]
        if len(newer) < VERSIONS_BEHIND_ALERT:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} is {len(newer)} releases behind on CC Sync (it is running "
            f"{e.get('companion_version')}, current is "
            f"{e.get('current_companion_version') or 'unknown'}). Every fix "
            f"since then is missing on that computer, including ones that "
            f"affect whether its footage syncs at all.",
            "On the dashboard: SETTINGS, PACKAGES, then [ UPDATE NOW ] on that "
            "computer.",
            f"behind={len(newer)}"))
    return out


def _check_soak(ctx: Ctx) -> list[Finding]:
    """A staged build whose canary machine crashed or rolled itself back."""
    out = []
    for r in _rows(ctx.conn,
                   "SELECT platform, version FROM companion_packages "
                   "WHERE kind='companion' AND rollout='staged' "
                   "AND (retracted_at IS NULL OR retracted_at='')"):
        try:
            state = db.soak_state(ctx.conn, str(r["platform"]), str(r["version"]),
                                  db.DEFAULT_SOAK_MINUTES, now=ctx.now)
        except sqlite3.Error:
            continue
        if not (state.get("crashes") or state.get("reverted")):
            continue
        out.append(_f(
            f"{r['version']} ({r['platform']})",
            f"The build being trialled on one computer before the fleet gets "
            f"it, {r['version']}, has {state.get('crashes')} crash(es) and "
            f"{state.get('reverted')} computer(s) that put themselves back on "
            f"the old build. It must not be handed to everybody.",
            "On the dashboard: SETTINGS, PACKAGES, and recall that build.",
            json.dumps(state.get("detail") or [], sort_keys=True)[:300]))
    return out


def _check_retracted_running(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        reason = e.get("companion_retracted_reason")
        if reason is None:
            continue
        who = ctx.name(_who(e))
        out.append(_f(
            who,
            f"{who} is still running {e.get('companion_version')}, a build that "
            f"has been recalled. Stopping it being offered to new computers "
            f"says nothing about the ones already on it, which are the ones a "
            f"recall is about.",
            "On the dashboard: SETTINGS, PACKAGES, then [ UPDATE NOW ] on that "
            "computer to move it onto a good build.",
            str(reason or "no reason given")))
    return out


def _check_key_drain(ctx: Ctx) -> list[Finding]:
    stale = {k: v for k, v in (ctx.retired_keys or {}).items()
             if (_age(v, ctx.now) or 0) >= KEY_DRAIN_DAYS * 86400}
    if not stale:
        return []
    return [_f(
        "sign-in key rotation",
        f"{len(stale)} computer(s) are still identifying themselves with the "
        f"OLD server key, more than {KEY_DRAIN_DAYS} days after it was "
        f"rotated. The moment the old key is removed, every one of them stops "
        f"being able to report and disappears from this page.",
        "Ask those editors to click Sign in on the CC Sync tray before the old "
        "key is dropped.",
        ", ".join(sorted(stale)[:20]))]


def _check_weekly_send(ctx: Ctx) -> list[Finding]:
    """The report's own delivery. An alerting system whose last message failed
    is the one fault nothing else can tell you about.

    Silent on a site whose sink is `none`: `run_cycle` records THAT case
    `ok=1` ("generated, not sent") directly rather than through `send`, so
    this only fires when a CONFIGURED sink actually failed (finding 2,
    resilience sweep 2026-08-28 fix pass)."""
    weekly = [r for r in db.fetch_alerts(ctx.conn, limit=200)
              if r.get("kind") == KIND_WEEKLY]
    if not weekly or weekly[0].get("ok"):
        return []
    row = weekly[0]
    return [_f(
        "the weekly report",
        f"The weekly fleet report could not be delivered "
        f"({_age_words(row.get('at'), ctx.now)}). Nobody is being told "
        f"anything by mail, including the alerts on this page.",
        "On the dashboard: SETTINGS, ALERTS, then [ SEND A TEST ] and fix what "
        "it says.",
        str(row.get("detail") or ""))]


def _check_invariants(ctx: Ctx) -> list[Finding]:
    """A fact this system relies on has stopped being true (SYS-9, wave 5).

    Reads the rows `invariants.run_cycle` wrote in the collector kind that
    runs immediately before this one; it does not re-evaluate anything, for
    the reason `Ctx`'s docstring gives -- the checks walk the tree and the
    registry, and a scan that ran them again per `/api/v1/health` call would
    be a scan somebody turns off. `_rows`' rule applies: a database migrated
    by an older build has no such table, and that reads as nothing to report
    HERE, because the invariant page says so for itself.

    ONE finding per broken subject, and the invariant's own consequence
    sentence is the diagnosis: the wording an owner needs was written once,
    in the registry, and must not be re-invented here.
    """
    from . import invariants

    out = []
    for row in db.broken_invariants(ctx.conn):
        inv = invariants.BY_KEY.get(str(row.get("invariant") or ""))
        if inv is None:
            continue
        out.append(_f(
            f"{inv.key}: {row.get('subject')}",
            f"{inv.consequence} This server checks that {inv.title}, and as of "
            f"{_age_words(row.get('checked_at'), ctx.now)} it is not true.",
            inv.fix,
            str(row.get("detail") or "")))
    return out


def _protection_findings(ctx: Ctx, wanted: tuple[str, ...]) -> list[Finding]:
    """The protection panel's lines, as alerts (SYS-14, wave 5).

    Reads the last stored pass exactly as `_check_invariants` reads the
    invariant ledger: the pass itself asks the NAS, and a scan that re-asked
    per `/api/v1/health` call would be a scan somebody turns off. A database
    an older build migrated has no stored pass at all, which reads as nothing
    to report HERE because the panel says so for itself.

    The line's own `consequence` sentence is the diagnosis: the wording was
    written once, in the registry, and must not be re-invented here.
    """
    from . import protection

    view = protection.page_view(ctx.conn)
    if not view["checked_at"]:
        # No pass has ever run here (a fresh boot, or a database an older
        # build migrated). The PANEL renders every line as CANNOT VERIFY, as
        # it must, but alerting on that would mail every new deployment eight
        # findings before the collector's first slow cycle.
        return []
    out = []
    for row in view["lines"]:
        if row["state"] not in wanted:
            continue
        line = protection.BY_KEY.get(row["key"])
        if line is None:
            continue
        if row["state"] == protection.BROKEN:
            diagnosis = (f"{line.consequence} This server checks that {line.title}, "
                         f"and it cannot see that it is.")
        else:
            diagnosis = (f"This server cannot confirm that {line.title}. "
                         f"{line.consequence} Treat it as unchecked, not as fine.")
        out.append(_f(line.key, diagnosis, line.fix, str(row.get("detail") or "")))
    return out


def _check_protection_missing(ctx: Ctx) -> list[Finding]:
    from . import protection

    return _protection_findings(ctx, (protection.BROKEN,))


def _check_protection_unverifiable(ctx: Ctx) -> list[Finding]:
    """Amber-forever, said ONCE. A warn is stated once and not repeated until
    it has cleared and come back, which is what makes a DSM site's permanent
    "cannot verify, confirm in DSM" honest rather than nagging."""
    from . import protection

    return _protection_findings(ctx, (protection.NOT_CHECKED, protection.CHECK_FAILED))


def _check_red_unexplained(ctx: Ctx) -> list[Finding]:
    """The catch-all. Runs LAST, and only for machines no other check named.

    This is the one that turns "green while dead" into a message: a computer
    that has been red for an hour and about which this server can say nothing
    specific is still a computer whose editor is not syncing.
    """
    out = []
    for e in ctx.editors:
        who = _who(e)
        if who in ctx.named or e.get("status") != health.RED:
            continue
        ages = [a for a in (_age(l.get("state_since"), ctx.now)
                            for l in (e.get("lanes") or []) if isinstance(l, Mapping))
                if a is not None]
        age = max(ages) if ages else _age(e.get("received_at"), ctx.now)
        if age is None or age < RED_UNEXPLAINED_SECONDS:
            continue
        why = (e.get("why") or {}).get("sentence")
        out.append(_f(
            who,
            (why or f"{who} has been showing a problem for "
                    f"{_duration_words(age)} and this dashboard cannot say "
                    f"which. It is not syncing normally.")
            + " Nothing more specific could be worked out from what that "
              "computer has reported.",
            "Open that computer's row on the FLEET page and press [ ASK WHY ], "
            "then send us the diagnostics it returns.",
            f"status={e.get('status')} reason={e.get('status_reason') or ''}"))
    return out


# The registry. ORDER MATTERS in exactly one way: `red_unexplained` is last,
# because it reports only what the specific kinds above it did not name.
ALERT_KINDS: tuple[AlertKind, ...] = (
    AlertKind("breaker_tripped", SEV_ERROR, "proxy download stopped itself",
              "a computer's proxy download brake", _check_breaker),
    AlertKind("fleet_halt", SEV_WARN, "syncing is halted for the whole fleet",
              "the fleet halt", _check_fleet_halt),
    AlertKind("fleet_halt_expired", SEV_WARN, "a fleet halt expired by itself",
              "a fleet halt past its expiry", _check_fleet_halt_expired),
    AlertKind("disk_park", SEV_ERROR, "a computer parked its downloads for space",
              "a computer parked below its disk floor", _check_disk_park),
    AlertKind("disk_low", SEV_ERROR, "a computer is running out of space",
              "free space on editors' sync drives", _check_disk_low),
    AlertKind("machine_silent", SEV_ERROR, "a computer has gone quiet",
              "computers silent for more than a day", _check_silent),
    AlertKind("report_refused", SEV_ERROR, "a computer is being turned away",
              "computers this server is refusing", _check_report_refused),
    AlertKind("clock_skew", SEV_ERROR, "a computer's clock is wrong",
              "clocks more than five minutes out", _check_clock_skew),
    AlertKind("engine_down", SEV_ERROR, "the sync engine is down on a computer",
              "a computer's sync engine down for an hour", _check_engine_down),
    AlertKind("nas_engine_down", SEV_ERROR, "the server's sync engine is unreachable",
              "the server's own sync engine", _check_nas_engine),
    AlertKind("lane_stalled", SEV_ERROR, "a sync lane is stuck",
              "lanes busy with nothing moving", _check_lane_stalled),
    AlertKind("lane_error", SEV_ERROR, "a sync lane has been failing",
              "lanes in error for an hour", _check_lane_error),
    AlertKind("folders_unfiltered", SEV_WARN, "a shared folder has no filter",
              "shared folders with no ignore filter", _check_folders_unfiltered),
    AlertKind("thread_restarts", SEV_WARN, "CC Sync keeps restarting itself",
              "computers restarting their own sync threads", _check_restarts),
    AlertKind("crashes", SEV_WARN, "background tasks have crashed",
              "crash reports on editors' computers", _check_crashes),
    AlertKind("upgrade_failed", SEV_ERROR, "an update will not install",
              "computers failing the same update", _check_upgrade_failed),
    AlertKind("upgrade_reverted", SEV_WARN, "a computer rolled an update back",
              "computers that rolled a build back", _check_upgrade_reverted),
    AlertKind("collector_kind_failed", SEV_ERROR, "a server background job is failing",
              "the server's background jobs", _check_collector_kinds),
    AlertKind("collector_stale", SEV_ERROR, "the server's collector has stopped",
              "the collector's own liveness", _check_collector_stale),
    AlertKind("watchdog_restart", SEV_ERROR, "the server restarted its collector",
              "collector watchdog restarts", _check_watchdog),
    AlertKind("enforce_refusal", SEV_ERROR, "a sharing change was refused",
              "the sharing blast-radius brake", _check_enforce_refusal),
    AlertKind("deactivation_refusal", SEV_ERROR, "a mass project deactivation was refused",
              "the project deactivation brake", _check_deactivation_refusal),
    AlertKind("enforce_plan", SEV_WARN, "a sharing change is held",
              "held sharing plans", _check_enforce_plan),
    AlertKind("ignored_sections", SEV_WARN, "computers are reporting things nobody reads",
              "report sections this build drops", _check_ignored_sections),
    AlertKind("feed_stale", SEV_WARN, "this dashboard cannot check for updates",
              "the vendor update feed", _check_feed_stale),
    AlertKind("feed_runtime_mismatch", SEV_WARN, "updates cannot install on this NAS",
              "offered builds against this container", _check_feed_runtime_mismatch),
    AlertKind("data_disk", SEV_ERROR, "the server is running out of space",
              "free space on the server's own volume", _check_data_disk),
    AlertKind("nas_tree", SEV_ERROR, "the project tree is missing",
              "the project tree canary", _check_nas_tree),
    AlertKind("notice_error", SEV_ERROR, "the server found a problem",
              "open problems the server recorded", _check_notices),
    AlertKind("out_of_tree", SEV_WARN, "footage is outside the tree",
              "clips referenced from outside the tree", _check_out_of_tree),
    AlertKind("stray_projects", SEV_WARN, "project folders outside the tree",
              "stray project folders", _check_stray_projects),
    AlertKind("moved_project_dir", SEV_WARN, "a project folder has moved",
              "project folders not where the tree expects", _check_moved_project_dirs),
    AlertKind("ingest_staging", SEV_WARN, "footage is waiting in a drop folder",
              "unfiled footage in drop folders", _check_ingest_staging),
    AlertKind("file_move_expired", SEV_WARN, "a file move was never confirmed",
              "file moves a computer never answered", _check_file_moves),
    AlertKind("versions_behind", SEV_WARN, "a computer is several releases behind",
              "computers behind on CC Sync", _check_versions_behind),
    AlertKind("soak_failed", SEV_WARN, "a trial build is failing",
              "builds on trial before the fleet", _check_soak),
    AlertKind("retracted_running", SEV_ERROR, "a recalled build is still running",
              "computers on recalled builds", _check_retracted_running),
    AlertKind("key_drain", SEV_WARN, "computers are still on the old sign-in key",
              "the sign-in key rotation drain", _check_key_drain),
    AlertKind("weekly_send_failed", SEV_ERROR, "the weekly report could not be sent",
              "the alert channel itself", _check_weekly_send),
    AlertKind("invariant_broken", SEV_ERROR, "something this system relies on is not true",
              "the invariant checks (SYS-9)", _check_invariants),
    AlertKind("protection_missing", SEV_ERROR, "a safety net is not there",
              "the protection panel (SYS-14)", _check_protection_missing),
    AlertKind("protection_unverifiable", SEV_WARN,
              "a safety net this server cannot check",
              "safety mechanisms this server can verify", _check_protection_unverifiable),
    AlertKind("red_unexplained", SEV_ERROR, "a computer is not syncing",
              "computers red with no specific cause", _check_red_unexplained),
)

KIND_BY_NAME: dict[str, AlertKind] = {k.kind: k for k in ALERT_KINDS}

# The one kind that is not in the registry, because it is about the registry:
# a check that raised. Fail in a NAMED direction (WAVE1_RULES): a check that
# could not run must never read as a check that found nothing.
CHECK_FAILED = AlertKind(
    "check_failed", SEV_ERROR, "a health check could not run",
    "every check ran", lambda ctx: [])


def scan(conn: sqlite3.Connection, settings: Any, now: str,
         *, watchdog_restarts: int = 0) -> list[dict[str, Any]]:
    """Every condition that is true RIGHT NOW, as a flat list.

    PURE with respect to delivery: the dedup, the sink and the record are
    `deliver`'s. That separation is what lets the Alerts page and
    `/api/v1/health` show what is open on a site whose sink is "none".
    """
    findings: list[dict[str, Any]] = []
    try:
        ctx = Ctx(conn, settings, now)
    except Exception as exc:                                        # noqa: BLE001
        log.exception("alerts: could not gather the scan context")
        return [{
            "kind": CHECK_FAILED.kind, "severity": SEV_ERROR,
            "title": CHECK_FAILED.title, "subject": "the whole scan",
            "diagnosis": ("This server could not read its own state to check "
                          "whether anything is wrong, so nothing below has "
                          "been checked."),
            "fix": "Send us the container log from the NAS.",
            "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
        }]
    if watchdog_restarts:
        findings.append({
            "kind": "watchdog_restart", "severity": SEV_ERROR,
            "title": KIND_BY_NAME["watchdog_restart"].title,
            "subject": "the server",
            "diagnosis": (
                f"The server's background collector stopped and had to be "
                f"restarted {watchdog_restarts} time(s). While it was down, "
                f"nothing shared newly ticked projects and every number on the "
                f"fleet page was ageing without changing."),
            "fix": ("If this keeps happening, restart the ccsync container on "
                    "the NAS and send us the container log."),
            "detail": f"restarts={watchdog_restarts}",
        })
    for kind in ALERT_KINDS:
        try:
            results = kind.check(ctx)
        except Exception as exc:                                    # noqa: BLE001
            log.exception("alerts: check %s failed", kind.kind)
            findings.append({
                "kind": CHECK_FAILED.kind, "severity": SEV_ERROR,
                "title": CHECK_FAILED.title, "subject": kind.kind,
                "diagnosis": (
                    f"The check for '{kind.what}' could not run, so this "
                    f"server does not know whether that is all right. Treat it "
                    f"as unchecked, not as fine."),
                "fix": "Send us the container log from the NAS.",
                "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
            })
            continue
        for finding in results[:MAX_FINDINGS_PER_KIND]:
            findings.append({
                "kind": kind.kind, "severity": kind.severity, "title": kind.title,
                **finding,
            })
    return findings


def open_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    """{"error": n, "warn": n} for /api/v1/health and the topbar."""
    counts = {SEV_ERROR: 0, SEV_WARN: 0}
    for finding in findings:
        counts[finding.get("severity", SEV_WARN)] = counts.get(
            finding.get("severity", SEV_WARN), 0) + 1
    return counts


# ------------------------------------------------------------- the composers

def compose_alert(kind: str, subject: str, detail: str) -> tuple[str, str]:
    """(mail subject, plain text) for one alert.

    PURE, and the reason `send` takes a subject and a text rather than a
    template: what an alert IS and how it is delivered are separate decisions,
    and only the first is worth a test. `detail` is the whole body a check
    composed (diagnosis, then fix, then the technical line).
    """
    title = KIND_BY_NAME[kind].title if kind in KIND_BY_NAME else kind
    line = f"CC Sync: {title} - {subject}" if subject else f"CC Sync: {title}"
    body = [line, ""]
    if detail:
        body.append(detail)
        body.append("")
    body.append("Open the CC Sync dashboard for the full picture.")
    return line, "\n".join(body)[:MAX_BODY_CHARS]


def _finding_body(finding: Mapping[str, Any]) -> str:
    parts = [str(finding.get("diagnosis") or "").strip()]
    fix = str(finding.get("fix") or "").strip()
    if fix:
        parts.append(f"What to do: {fix}")
    detail = str(finding.get("detail") or "").strip()
    if detail:
        parts.append(f"Detail: {detail}")
    return "\n\n".join(p for p in parts if p)


def compose_recovered(kind: str, subject: str) -> tuple[str, str]:
    title = KIND_BY_NAME[kind].title if kind in KIND_BY_NAME else kind
    line = f"CC Sync: cleared - {title} - {subject}" if subject else \
        f"CC Sync: cleared - {title}"
    return line, (f"{line}\n\nThis has cleared on its own or somebody fixed it. "
                  f"No action is needed.\n")


def _lane_bytes_section(conn: sqlite3.Connection) -> list[str]:
    """Bytes moved per lane per machine, IF the lane tables carry it.

    They do not today: lane_report_current holds queued/transferring counts
    and no byte total, so this fleet has no throughput history at all and the
    section is omitted rather than invented. Written as a live probe so the
    day a lane report grows the column, the weekly report grows the section
    with no second edit here.
    """
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(lane_report_current)")}
    except sqlite3.Error:
        return []
    column = next((c for c in ("bytes_moved", "bytes", "transferred_bytes")
                   if c in columns), None)
    if column is None:
        return []
    rows = conn.execute(
        f"SELECT editor_username, machine, lane, {column} AS moved "
        f"FROM lane_report_current WHERE {column} IS NOT NULL "
        f"ORDER BY editor_username, machine, lane"
    ).fetchall()
    if not rows:
        return []
    lines = ["BYTES MOVED (per lane, since that lane last reset)"]
    for r in rows:
        lines.append(f"  {r['editor_username']}/{r['machine']} {r['lane']}: "
                     f"{_bytes_words(r['moved'])}")
    return lines + [""]


def compose_weekly(
    conn: sqlite3.Connection, now: str, settings: Any = None,
) -> tuple[str, str]:
    """(subject, plain text) for this week's fleet health report.

    Composed ENTIRELY from state that already exists. `build_editors_view` is
    reached through Ctx rather than imported at module scope because api.py
    imports this module for its routes; the cycle is real and this is the end
    that can afford to be lazy.
    """
    findings = scan(conn, settings, now)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        by_kind.setdefault(finding["kind"], []).append(finding)
    counts = open_counts(findings)

    ctx_fleet: dict[str, Any]
    try:
        from .api import build_editors_view

        ctx_fleet = build_editors_view(conn, now)
    except Exception:                                               # noqa: BLE001
        log.exception("alerts: the weekly report could not read the fleet")
        ctx_fleet = {"editors": []}
    editors = list(ctx_fleet.get("editors") or [])
    week_ago = _iso_minus(now, 7 * 24 * 3600)
    lines: list[str] = []

    subject = (f"CC Sync weekly: {len(editors)} computer(s), "
               f"{counts.get(SEV_ERROR, 0)} problem(s), "
               f"{counts.get(SEV_WARN, 0)} thing(s) to look at")

    lines.append(f"Fleet health for the week ending {now}.")
    lines.append(f"{len(editors)} computer(s) reporting.")
    lines.append("")

    # 1. Everything wrong right now, worst first, each as its own diagnosis.
    for severity, heading in ((SEV_ERROR, "PROBLEMS"),
                              (SEV_WARN, "THINGS TO LOOK AT")):
        rows = [f for f in findings if f.get("severity") == severity]
        lines.append(f"{heading} ({len(rows)})")
        if not rows:
            lines.append("  none.")
        for finding in rows:
            lines.append(f"  [{finding['kind']}] {finding['subject']}")
            for part in _finding_body(finding).splitlines():
                if part.strip():
                    lines.append(f"      {part.strip()}")
        lines.append("")

    # 2. Build coverage. "0.9.55: 6 of 8" plus every laggard by name and by
    #    how long it has been behind, which turns "somebody should upgrade
    #    that Mac" into a date.
    lines.append("BUILDS")
    by_version: dict[str, list[dict[str, Any]]] = {}
    for entry in editors:
        by_version.setdefault(entry.get("companion_version") or "unknown", []).append(entry)
    total = len(editors)
    for version, rows in sorted(by_version.items()):
        lines.append(f"  {version}: {len(rows)} of {total} machine(s)")
    for entry in editors:
        if not entry.get("companion_outdated") and not entry.get("companion_version_unknown"):
            continue
        lines.append(
            f"  {_who(entry)} has been on "
            f"{entry.get('companion_version') or 'an unreported build'} since "
            f"{_age_words(entry.get('companion_version_since'), now)}; current "
            f"for {entry.get('platform') or '?'} is "
            f"{entry.get('current_companion_version') or 'nothing published'}")
    lines.append("")

    # 3. What changed this week, from the audit ledger, beside the alarms:
    #    an incident review needs the alarm AND who touched what around it.
    audit_rows = db.audit_since(conn, week_ago, limit=200)
    lines.append(f"WHAT CHANGED THIS WEEK ({len(audit_rows)} entries)")
    for row in audit_rows[:40]:
        lines.append(f"  {row['at']} {row['actor']} {row['action']} {row['subject']}")
    if len(audit_rows) > 40:
        lines.append(f"  ... and {len(audit_rows) - 40} more on the TIMELINE page.")
    if not audit_rows:
        lines.append("  nothing.")
    lines.append("")

    alerts_sent = db.fetch_alerts(conn, limit=50, since=week_ago)
    if alerts_sent:
        lines.append("ALERTS SENT THIS WEEK")
        for row in alerts_sent:
            failed = "" if row["ok"] else f" (SEND FAILED: {row['detail'] or '?'})"
            lines.append(f"  {row['at']} [{row['kind']}] {row['subject']}{failed}")
        lines.append("")

    lines += _lane_bytes_section(conn)

    # 3b. What is protected, and what only looks protected (SYS-14, wave 5).
    #     A STANDING block, printed whether or not anything is wrong: "no
    #     snapshot schedule is configured on this NAS" has to be a line in
    #     every report until it stops being true, and a block that appeared
    #     only on bad weeks would make its absence read as good news.
    try:
        from . import protection

        lines += protection.weekly_lines(conn)
    except Exception:                                               # noqa: BLE001
        log.exception("alerts: the weekly report could not read the protection panel")
        lines.append("WHAT IS PROTECTED: this section could not be read this week. "
                     "Treat it as unchecked, not as fine.")
        lines.append("")

    # 4. Trash, when a machine reported one. .stversions is NOT here: no
    #    companion measures it, and a zero we did not measure would read as
    #    "nothing to clean up".
    trash = [e for e in editors if (e.get("guard") or {}).get("trash_bytes")]
    if trash:
        lines.append("RECOVERABLE FILES IN .ccsync-trash")
        for entry in trash:
            guard = entry["guard"]
            lines.append(f"  {_who(entry)}: {_bytes_words(guard.get('trash_bytes'))} "
                         f"in {guard.get('trash_count') or '?'} file(s)")
        lines.append("")

    # 5. Silence has to be PROVABLY checked. Without this list, a clean report
    #    is indistinguishable from a report whose checks all crashed.
    clean = [k for k in ALERT_KINDS if not by_kind.get(k.kind)]
    lines.append(f"CHECKED AND FOUND NOTHING WRONG ({len(clean)} of "
                 f"{len(ALERT_KINDS)})")
    for kind in clean:
        lines.append(f"  ok - {kind.what}")
    failed_checks = by_kind.get(CHECK_FAILED.kind) or []
    if failed_checks:
        lines.append("")
        lines.append(f"COULD NOT BE CHECKED ({len(failed_checks)})")
        for finding in failed_checks:
            lines.append(f"  {finding['subject']}: {finding['detail']}")
    lines.append("")

    lines.append("This report is composed from what the dashboard already "
                 "knows. Anything it could not read is named above rather "
                 "than left out.")
    return subject, "\n".join(lines)[:MAX_BODY_CHARS]


# ------------------------------------------------------------------- the sink

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """No dashboard call follows a redirect (docs/GOTCHAS.md §12). Applied
    here because an alert body names the fleet's editors, machines and exactly
    what is broken, and a 302 is somebody else choosing where that goes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _webhook_opener():
    """Overridable so tests stub the OPENER, never urlopen (GOTCHAS §12)."""
    return urllib.request.build_opener(_NoRedirect)


def _send_webhook(url: str, subject: str, text: str) -> str:
    if not url:
        raise AlertError("no webhook URL is set")
    if not url.lower().startswith("https://"):
        # Re-checked at SEND time and not only at save time: a row written by
        # an older build, a hand-edited database or a restored backup must not
        # be able to put a fleet's state on the wire in the clear.
        raise AlertError("the webhook URL must be https")
    body = json.dumps({"subject": subject, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "ccsync-dashboard-alerts"})
    try:
        with _webhook_opener().open(request, timeout=SEND_TIMEOUT_SECONDS) as resp:
            resp.read(4096)
            return f"HTTP {getattr(resp, 'status', 200)}"
    except urllib.error.HTTPError as exc:
        raise AlertError(f"the webhook answered HTTP {exc.code}") from None
    except (TimeoutError, OSError) as exc:
        raise AlertError(f"could not reach the webhook "
                         f"({type(exc).__name__}: {str(exc)[:160]})") from None


def _smtp_class():
    """The class `_send_smtp` builds its connection with. Its own function so
    the suite can substitute a fake without a live server and without monkeying
    with smtplib's module globals."""
    return smtplib.SMTP


def _send_smtp(values: Mapping[str, str], password: str,
               subject: str, text: str) -> str:
    host = (values.get("alerts_smtp_host") or "").strip()
    sender = (values.get("alerts_smtp_from") or "").strip()
    recipients = [a.strip() for a in
                  (values.get("alerts_smtp_to") or "").replace(";", ",").split(",")
                  if a.strip()]
    if not host:
        raise AlertError("no SMTP host is set")
    if not sender or not recipients:
        raise AlertError("SMTP needs a FROM address and at least one TO address")
    port = int(values.get("alerts_smtp_port") or 587)
    user = (values.get("alerts_smtp_user") or "").strip()
    use_tls = (values.get("alerts_smtp_tls") or "1") == "1"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text)

    try:
        with _smtp_class()(host, port, timeout=SEND_TIMEOUT_SECONDS) as client:
            if use_tls:
                client.starttls()
            if user:
                client.login(user, password)
            client.send_message(message)
    except smtplib.SMTPAuthenticationError:
        # The server's own message can echo the username; the password can
        # never reach a log or a page from here.
        raise AlertError("the mail server refused the sign-in") from None
    except (smtplib.SMTPException, TimeoutError, OSError) as exc:
        raise AlertError(f"could not send through {host} "
                         f"({type(exc).__name__}: {str(exc)[:160]})") from None
    return ", ".join(recipients)


def send(
    conn: sqlite3.Connection, settings: Any, subject: str, text: str,
    *, kind: str = KIND_TEST, dedup_subject: str | None = None,
    now: str | None = None, dedup: bool = True,
) -> dict[str, Any]:
    """Deliver one message through this site's sink and record the attempt.

    Returns {"ok", "sink", "sent_to", "detail", "deduped"} and NEVER raises for
    a delivery failure: this is called from the collector thread, and an SMTP
    server that is down must not take the poll cycle with it. The failure is
    recorded in `alert_log` (ok=0) so the Alerts page can say the channel has
    been refusing since Tuesday, which is the one thing worse than no alerts:
    believing you have them.

    The dedup reads ANY row, not only a successful one, on purpose: with the
    sink misconfigured, an ok-only window would re-attempt every condition
    every cycle and fill the ledger with failures nobody can read.
    """
    now = now or db.utcnow_iso()
    values = get_settings(conn)
    sink = values.get("alerts_sink") or SINK_NONE
    key = subject if dedup_subject is None else dedup_subject
    if dedup and db.alert_recently_sent(conn, kind, key, now, ok_only=False):
        return {"ok": True, "sink": sink, "sent_to": "",
                "detail": "already sent today", "deduped": True}
    if sink == SINK_NONE:
        # Recorded, not silently dropped: "we composed an alert and this site
        # has no sink" is a fact the Alerts page shows, and it is the honest
        # answer to "why did nobody get told".
        db.record_alert(conn, kind, key, "", False, "no sink configured", now)
        return {"ok": False, "sink": sink, "sent_to": "",
                "detail": "no sink configured", "deduped": False}
    try:
        if sink == SINK_WEBHOOK:
            sent_to = (values.get("alerts_webhook_url") or "").strip()
            detail = _send_webhook(sent_to, subject, text)
        else:
            password, _source = read_password(settings)
            sent_to = _send_smtp(values, password, subject, text)
            detail = "sent"
    except AlertError as exc:
        log.warning("alerts: %s alert could not be delivered: %s", kind, exc)
        db.record_alert(conn, kind, key, "", False, str(exc), now)
        return {"ok": False, "sink": sink, "sent_to": "", "detail": str(exc),
                "deduped": False}
    except Exception as exc:                                        # noqa: BLE001
        # Fault isolation of last resort: this runs inside the collector's
        # cycle, and no sink's surprise may end that thread.
        log.exception("alerts: unexpected failure delivering a %s alert", kind)
        db.record_alert(conn, kind, key, "", False,
                        f"{type(exc).__name__}: {str(exc)[:160]}", now)
        return {"ok": False, "sink": sink, "sent_to": "",
                "detail": f"{type(exc).__name__}", "deduped": False}
    db.record_alert(conn, kind, key, sent_to, True, detail, now)
    return {"ok": True, "sink": sink, "sent_to": sent_to, "detail": detail,
            "deduped": False}


def _is_open(conn: sqlite3.Connection, kind: str, subject: str) -> bool:
    """Whether this (kind, subject) is currently in an alerted state.

    Two timestamps, no third table: the last alert against the last RECOVERED
    record. Durable across a container replacement, which is the whole reason
    it is not a set in memory.
    """
    raised = db.last_alert_at(conn, kind, subject, ok_only=False)
    if not raised:
        return False
    cleared = db.last_alert_at(conn, kind + RECOVERED_SUFFIX, subject, ok_only=False)
    if not cleared:
        return True
    try:
        return db.parse_iso(cleared) < db.parse_iso(raised)
    except (ValueError, TypeError):
        return True


def deliver(
    conn: sqlite3.Connection, settings: Any, findings: list[dict[str, Any]], now: str,
) -> dict[str, Any]:
    """Send what is new, re-send what is still an error, say what recovered.

    The repeat rule is the SEVERITY's: an "error" repeats once a day for as
    long as it is true, because an outage nobody acted on must not go quiet; a
    "warn" is said once and not again until it has cleared and come back.
    """
    sent = failed = recovered = 0
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        kind = str(finding["kind"])
        subject = str(finding["subject"])
        seen.add((kind, subject))
        severity = finding.get("severity", SEV_WARN)
        was_open = _is_open(conn, kind, subject)
        if was_open and severity != SEV_ERROR:
            continue
        mail_subject, text = compose_alert(kind, subject, _finding_body(finding))
        result = send(conn, settings, mail_subject, text, kind=kind,
                      dedup_subject=subject, now=now,
                      dedup=was_open or severity != SEV_ERROR)
        if result["deduped"]:
            continue
        sent += 1 if result["ok"] else 0
        failed += 0 if result["ok"] else 1

    # RECOVERED. Only for subjects this scan actually covered: a kind whose
    # check FAILED this cycle has told us nothing about its subjects, so
    # declaring them recovered would be the "could not check rendered as fine"
    # mistake in its purest form.
    checked_kinds = {k.kind for k in ALERT_KINDS} - {
        f["subject"] for f in findings if f["kind"] == CHECK_FAILED.kind}
    for kind, subject in _open_subjects(conn, checked_kinds):
        if (kind, subject) in seen:
            continue
        mail_subject, text = compose_recovered(kind, subject)
        result = send(conn, settings, mail_subject, text,
                      kind=kind + RECOVERED_SUFFIX, dedup_subject=subject,
                      now=now, dedup=False)
        recovered += 1
        failed += 0 if result["ok"] else 1
    return {"sent": sent, "failed": failed, "recovered": recovered}


def _open_subjects(
    conn: sqlite3.Connection, kinds: set[str],
) -> list[tuple[str, str]]:
    """Every (kind, subject) currently in an alerted state, for the kinds
    given. One query over the ledger rather than one per subject."""
    subjects = {(str(r["kind"]), str(r["subject"]))
                for r in db.fetch_alerts(conn, limit=500)
                if str(r["kind"]) in kinds}
    return [(kind, subject) for kind, subject in sorted(subjects)
            if _is_open(conn, kind, subject)]


def run_cycle(
    conn: sqlite3.Connection, settings: Any, now: str,
    *, watchdog_restarts: int = 0,
) -> dict[str, Any]:
    """One alerts pass: scan, deliver, then the weekly report if it is owed.

    Returns a summary the collector hands to `_timed` as its note, so a pass
    that delivered nothing because this site has no sink says so on the
    collector health panel rather than reading as a clean cycle.
    """
    findings = scan(conn, settings, now, watchdog_restarts=watchdog_restarts)
    result = deliver(conn, settings, findings, now)
    weekly = False
    if weekly_due(conn, now):
        subject, text = compose_weekly(conn, now, settings)
        sink = get_settings(conn).get("alerts_sink") or SINK_NONE
        if sink == SINK_NONE:
            # Finding 2 (resilience sweep 2026-08-28 fix pass). The vendor
            # default has no sink, so `send()` would record every weekly
            # attempt ok=0 "no sink configured" -- true of every OTHER
            # finding too (section 6 of the doc), but for the weekly report
            # specifically that made `_check_weekly_send` raise an error
            # finding every day from the first Monday on a site that has
            # never configured one, which is not "the alert channel is
            # broken". Recorded directly (not through `send`) as GENERATED,
            # not sent: still on the Alerts page's WHAT WAS SENT list for the
            # admin who turns a sink on later, `ok=1` so `_check_weekly_send`
            # stays quiet, and never counted as a delivery failure.
            # `weekly_send_failed` still fires the moment a CONFIGURED sink
            # fails to send it.
            db.record_alert(conn, KIND_WEEKLY, "weekly", "", True,
                            "generated, not sent (no sink configured)", now)
            weekly = True
        else:
            # dedup off: weekly_due IS the schedule, and a second gate keyed
            # on a subject line that changes every week would never fire
            # anyway.
            outcome = send(conn, settings, subject, text, kind=KIND_WEEKLY,
                           dedup_subject="weekly", now=now, dedup=False)
            weekly = bool(outcome["ok"])
            result["failed"] += 0 if outcome["ok"] else 1
    counts = open_counts(findings)
    # Finding 3 (resilience sweep 2026-08-28 fix pass): the LAST scan's open
    # counts, so the topbar chip (ui._alert_counts_safe) can show a number on
    # every page without re-running forty checks per render. Written here,
    # the one place a scan's findings and its "this is now current" moment
    # coincide, and inside the same commit as the delivery records above so a
    # container killed between the two can never show a chip the ledger
    # disagrees with.
    db.meta_set_json(conn, db.META_ALERTS_OPEN, counts)
    conn.commit()
    note = None
    if result["failed"]:
        note = f"{result['failed']} alert(s) could not be delivered"
    elif counts.get(SEV_ERROR):
        note = f"{counts[SEV_ERROR]} problem(s) open"
    return {**result, "weekly": weekly, "open": counts, "note": note}
