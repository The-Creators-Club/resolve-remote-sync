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
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Mapping

from . import db, health, mount_status

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
# DDIAG-17 (2026-09-04): the dead-man's beat. Scheduled like the weekly
# report and for the same reason NOT a registry kind - it reports no
# condition, so it must never be counted as a raised problem, never be
# recovered and never appear on CURRENTLY OPEN.
KIND_HEARTBEAT = "heartbeat"

# The suffix a RECOVERED record is filed under. A separate kind namespace
# rather than a column, so "is this subject currently alerted" is one
# comparison of two timestamps and no migration.
RECOVERED_SUFFIX = ".ok"

# DDIAG-4 (2026-09-04): where a row that was NEVER SENT goes when a sink is
# finally configured. See `_requeue_undelivered`.
UNDELIVERED_SUFFIX = ".undelivered"

# The detail `send()` writes for a finding composed on a site with no sink.
# Matched as a string in `_requeue_undelivered`, so the two must agree.
NO_SINK_DETAIL = "no sink configured"

# A machine that has not reported for this long is silent. The same 24 h the
# finding names, and deliberately far above health.STALE_EDITOR_RED_SECONDS
# (6 h): the grid may redden at six hours, but waking somebody by mail wants a
# threshold no laptop lid closed over lunch can reach.
SILENT_SECONDS = 24 * 3600

# DDIAG-3 (2026-09-04). `machine_silent` is an ERROR, and an error repeats
# once a day for as long as it is true, so a laptop that was retired, rebuilt
# under a new hostname or taken on a three-week shoot mailed the owner the
# same sentence 21 times. After a fortnight of silence the computer is no
# longer this check's business: it is a standing notice on the home panel
# (`machine_forgotten`, filed by notices.py) and a [ FORGET ] button on the
# FLEET row, not a daily alarm. The give-up is deliberately far past the
# longest shoot anyone here has been on.
SILENT_GIVE_UP_DAYS = 14

# DDIAG-16 (2026-09-04). How recently the sink must have delivered SOMETHING
# for this server to believe it still works. A mailbox that started bouncing
# in March is the same hole as no sink at all, and the only place a failed
# send is stated is the Alerts page, which is where somebody who already
# trusts the alarm goes. 30 days is wider than any real quiet spell - the
# weekly report alone puts four successful sends inside it - so a window with
# nothing in it is evidence rather than a slow month.
SEND_EVIDENCE_MAX_AGE_SECONDS = 30 * 24 * 3600

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

# DDIAG-2 (2026-09-04). The fleet job queue, whose own module says "THE
# FAILURE MODE OF A SCHEDULER IS INVISIBLE: a scheduler that quietly assigns
# nothing looks exactly like a fleet with nothing to do", was diagnosed
# nowhere but /admin/jobs, which nothing links to from the home page. Six
# hours is deliberately long: an idle floor, a busy fleet and a machine that
# is asleep all legitimately leave work queued for an hour, and only a
# reason_code that no amount of waiting can change is worth a message.
JOBS_STARVED_SECONDS = 6 * 3600
# The window "the fleet gave up on some work" asks about, matching
# db.JOB_FINISHED_WINDOW_HOURS' day so the page and the alert count the same
# jobs.
JOBS_ABANDONED_HOURS = 24
# DDIAG-6: a pinned row held by this container's own worker whose heartbeat
# stopped. The executor beats every 10 s (cards_exec.POLL_SECONDS), so an
# hour of silence is a worker that is gone rather than a long encode.
PINNED_STALE_SECONDS = 3600

# REL-6 (2026-09-04). How long after a build was MADE CURRENT a fleet still
# sitting on the old one stops being a normal rollout and becomes a stalled
# one. Two days covers a weekend, a shoot and a laptop that was off; past it,
# a computer that has reported since and is still behind is not busy taking
# the update, it is not taking it.
ROLLOUT_STALLED_SECONDS = 48 * 3600
# REL-13: how far one platform's channel may fall behind another's before it
# is a finding. macOS bundles cannot be cross-built from Windows, so "the Mac
# half is owed" has been true across many ships and was recorded only as a
# yellow line in a terminal's scrollback.
PLATFORM_CHANNEL_STALE_SECONDS = 7 * 24 * 3600
PLATFORM_CHANNEL_STALE_BUILDS = 2

# BROLL-2: a b-roll ingest batch nobody is working on. The lease is minutes
# wide, so a day of no heartbeat is a batch whose companion went away for
# good rather than one between two clips.
BROLL_BATCH_STUCK_SECONDS = 24 * 3600
# How near its expiry a client link is worth a warning. A week is enough
# notice to ask the client whether they still need it, and short enough that
# the warning is about THIS link rather than a standing list.
BROLL_SHARE_EXPIRY_SECONDS = 7 * 24 * 3600

WEEKLY_WEEKDAY = 0          # Monday, datetime.weekday()
WEEKLY_HOUR = 8             # 08:00 site-local

# Wall-clock ceiling on ONE delivery. The collector is a single thread running
# every due kind in series (ops-efficiency-5's lesson): an SMTP server that
# hangs rather than refuses must not park enforce, connections and provision
# behind it.
SEND_TIMEOUT_SECONDS = 20.0

# DDIAG-1 (2026-09-04): a ceiling on the PASS, not on one send. The per-send
# ceiling above bounds each conversation; nothing bounded the run of them, and
# `scan()` legitimately produces dozens of findings on an unhappy fleet (40 per
# kind, 42 kinds, every error re-sending once a day). 46 sends against a relay
# that hangs rather than refuses is 920 s, which is past
# app.WATCHDOG_WEDGED_SECONDS (900 s): the watchdog then replaces the container
# with one that is due the same cycle, for ever. Deliberately far below that
# threshold, and safe to spend: an alert that is not sent this pass is still
# OPEN, so the next cycle offers it again.
ALERT_CYCLE_BUDGET_SECONDS = 120.0

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
    # bug-hunt-2026-09-03 dash-collector-3: an EXPLICIT opt-out for the site
    # whose internal relay presents a self-signed certificate. Default on:
    # the alternative shipped for everyone was an encrypted but
    # unauthenticated channel that the next statement hands an SMTP password
    # to. Never a silent fallback on a verification failure - that would look
    # verified and be worse than the bug it replaced.
    "alerts_smtp_verify_tls": "bool",
    "alerts_webhook_url": "https",
    "alerts_timezone": "str",
    "alerts_weekly": "bool",
    # DDIAG-17 (2026-09-04). Off by default: one mail a day is a cost the
    # owner opts into, and a heartbeat nobody asked for is the first rule a
    # mailbox filter learns.
    "alerts_heartbeat": "bool",
}

_DEFAULTS = {
    "alerts_sink": SINK_NONE,
    "alerts_smtp_port": "587",
    "alerts_smtp_tls": "1",
    "alerts_smtp_verify_tls": "1",
    "alerts_weekly": "1",
    "alerts_heartbeat": "0",
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
                             "(an alert body names your editors and computers)")
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
    was = get_settings(conn).get("alerts_sink") or SINK_NONE
    # bug-hunt-2026-09-03 dash-collector-5: the page renders the webhook URL
    # MASKED past its origin, so a form submitted with that field untouched
    # posts the mask back. Treat "the mask of what is stored" as "unchanged"
    # rather than writing a broken URL over a working one; a real edit never
    # produces a string with the mask's ellipsis in it (typed URLs are ASCII).
    if "alerts_webhook_url" in normalised:
        stored = get_settings(conn).get("alerts_webhook_url") or ""
        if stored and normalised["alerts_webhook_url"] == mask_url(stored):
            normalised["alerts_webhook_url"] = stored
    now = db.utcnow_iso()
    for key, value in normalised.items():
        conn.execute(
            "INSERT INTO site_settings (key, value, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (key, value, now, str(updated_by or "?")),
        )
    if was == SINK_NONE and (normalised.get("alerts_sink") or was) != SINK_NONE:
        _requeue_undelivered(conn)
    return normalised


def _requeue_undelivered(conn: sqlite3.Connection) -> int:
    """Make everything that is open today sendable again (DDIAG-4).

    On the vendor default every finding still gets an `alert_log` row, ok=0
    "no sink configured", deliberately: the page has to be able to answer
    "why was nobody told". But that row is ALSO what `_is_open` and the dedup
    window read, so the day an admin finally configures SMTP every warn that
    was already open counted as said, and would not be sent again until it had
    cleared and come back - on the one day the owner is most likely to be
    watching for a first message. 17 of the registry's kinds are warns.

    Those rows are re-filed under `<kind>.undelivered` instead of deleted:
    they stay on WHAT WAS SENT, where they are the honest record of a period
    with no channel, but they no longer make a subject look raised. The next
    scan therefore re-raises every open subject with a real sink behind it.

    Best effort by design - a database an older build migrated may have no
    `alert_log` at all, and a settings save must not fail on the bookkeeping
    about it. Returns how many rows were moved.
    """
    try:
        cur = conn.execute(
            "UPDATE alert_log SET kind = kind || ? "
            "WHERE ok = 0 AND detail = ? AND kind NOT LIKE ?",
            (UNDELIVERED_SUFFIX, NO_SINK_DETAIL, "%" + UNDELIVERED_SUFFIX))
    except sqlite3.Error:
        log.exception("alerts: could not re-open what was never delivered")
        return 0
    moved = int(cur.rowcount or 0)
    if moved:
        log.info("alerts: a sink was configured; %d finding(s) that were "
                 "never delivered will be raised again on the next check", moved)
    return moved


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


def url_origin(url: str) -> str:
    """`https://host[:port]` and nothing else (dash-collector-5).

    Every common receiver - Slack `hooks.slack.com/services/T…/B…/…`, Teams,
    Discord - puts the secret in the PATH, so the path is a bearer credential
    and the origin is the part it is safe to keep saying out loud.
    """
    url = str(url or "").strip()
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    # netloc, not hostname: a userinfo half would be a credential, and this
    # value is written to the ledger.
    host = parts.netloc.rsplit("@", 1)[-1]
    return f"{parts.scheme}://{host}"


def mask_url(url: str) -> str:
    """The origin, with everything past it replaced (dash-collector-5). The
    admin can still recognise which receiver is configured; a screenshot, an
    API response or the Alerts page cannot re-post to it."""
    url = str(url or "").strip()
    origin = url_origin(url)
    if not origin:
        return mask(url)
    return origin + "/…" if len(url) > len(origin) else origin


def settings_view(conn: sqlite3.Connection, settings: Any) -> dict[str, Any]:
    """What the page and the API may see. THE PASSWORD IS NEVER IN HERE, only
    whether one is set and where it came from.

    bug-hunt-2026-09-03 dash-collector-5: the webhook URL is a bearer
    credential too, so it is masked past its origin here. It is still STORED
    in `site_settings` - moving it to a file under <data>/secrets/ beside the
    SMTP password, so a database backup is not a working credential either, is
    an owner decision (a migration plus a second store), not something this
    fix takes on its own.
    """
    values = get_settings(conn)
    secret, source = read_password(settings)
    webhook = values.get("alerts_webhook_url") or ""
    values["alerts_webhook_url"] = mask_url(webhook)
    return {
        **values,
        "webhook_url_set": bool(webhook),
        "webhook_origin": url_origin(webhook),
        "sinks": list(SINKS),
        "password_set": bool(secret),
        "password_source": source,
        "password_mask": mask(secret),
        "timezone": timezone_name(conn),
    }

def sink_deliverable(conn: sqlite3.Connection, now: str = "") -> tuple[bool, str]:
    """Would anything this server finds right now actually reach a person?

    DDIAG-16 / SYS-1 (2026-09-04). The one answer three callers share: the
    `alerts_sink` protection line, invariant 15 (`alerts_deliverable`) and
    anything later that needs the same fact. Returns (ok, one line an owner
    can read) - never a code, because every caller of this renders the string
    straight to a person.

    Green needs BOTH halves. A sink that was configured once and has
    delivered nothing for a month is the same hole as no sink at all, and it
    is the more dangerous of the two because it feels safe.

    Raises `sqlite3.Error` if the ledger cannot be read at all, and
    ValueError/TypeError on a timestamp it cannot parse. That is not a False:
    a caller that cannot ask must render "not checked", never "no". The two
    callers today catch it and do exactly that.
    """
    now = now or db.utcnow_iso()
    sink = get_settings(conn).get("alerts_sink") or SINK_NONE
    if sink == SINK_NONE:
        return False, ("no mail server and no webhook is set, so nothing this "
                       "server finds is ever sent to anybody")
    ok_row = conn.execute(
        "SELECT at FROM alert_log WHERE ok = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    last_ok = str(ok_row["at"]) if ok_row else ""
    bad_row = conn.execute(
        "SELECT at, detail FROM alert_log WHERE ok = 0 AND detail <> ? "
        "ORDER BY id DESC LIMIT 1", (NO_SINK_DETAIL,)
    ).fetchone()
    # A row recorded while this site had no sink is not evidence about the
    # channel: it is the record of the setting it has just left behind.
    if not last_ok:
        if bad_row:
            return False, (f"the {sink} channel is set up and has never "
                           f"managed to send anything: "
                           f"{str(bad_row['detail'] or '')[:120]}")
        return False, (f"the {sink} channel is set up but nothing has ever "
                       f"been sent through it")
    if bad_row and str(bad_row["at"] or "") > last_ok:
        return False, (f"the last message this server tried to send did not "
                       f"go out: {str(bad_row['detail'] or '')[:120]}")
    age = db.age_seconds(last_ok, now)
    if age > SEND_EVIDENCE_MAX_AGE_SECONDS:
        return False, (f"nothing has been delivered through the {sink} "
                       f"channel since {last_ok[:10]}")
    return True, (f"the {sink} channel delivered something "
                  f"{int(max(0.0, age) // 3600)} hour(s) ago")


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


def heartbeat_due(conn: sqlite3.Connection, now: str) -> bool:
    """Whether today's proof of life is owed (DDIAG-17, 2026-09-04).

    ONE PER CALENDAR DAY in the site's own zone, and the comparison is the
    DATE of the last heartbeat row against today's - not "24 hours since the
    last one", which drifts an hour later every day until it lands in the
    middle of the night. Durable like `weekly_due`: the ledger decides, so a
    container replaced four times before lunch still sends one.

    Off unless a sink is set. A heartbeat that cannot be delivered is not a
    heartbeat, and recording one every cycle on a site with no sink would
    fill the ledger with the fact that it has no sink.
    """
    values = get_settings(conn)
    if (values.get("alerts_heartbeat") or "0") != "1":
        return False
    if (values.get("alerts_sink") or SINK_NONE) == SINK_NONE:
        return False
    zone, _name = _zone_or_utc(conn)
    try:
        today = db.parse_iso(now).astimezone(zone).date()
    except (ValueError, TypeError):
        return False
    last = db.last_alert_at(conn, KIND_HEARTBEAT, ok_only=False)
    if not last:
        return True
    try:
        return db.parse_iso(last).astimezone(zone).date() < today
    except (ValueError, TypeError):
        # The failure direction of a liveness beat is to send: silence is
        # what this feature exists to make meaningful.
        return True


def _machine_count(conn: sqlite3.Connection) -> int:
    """How many computers this server knows about. `_rows`' rule: a database
    an older build migrated has no `machines` table, and that reads as none
    rather than as an exception inside a delivery."""
    rows = _rows(conn, "SELECT COUNT(*) AS n FROM machines")
    return int(rows[0]["n"] or 0) if rows else 0


def compose_heartbeat(
    conn: sqlite3.Connection, counts: Mapping[str, int],
) -> tuple[str, str]:
    """The daily "still here" message (DDIAG-17).

    Every alert in this product is composed and sent BY the thing being
    watched, so a container that is off, a collector past its restart limit,
    a NAS that is powered down and a healthy fleet all produce the same
    experience: no mail. This is the one message whose ABSENCE is the
    information, which is why the body says so in the body: an owner who
    deletes these unread still learns the rule from the one that stopped.

    The counts are the ones `run_cycle` already has. Nothing is measured here.
    """
    machines = _machine_count(conn)
    errors = int(counts.get(SEV_ERROR) or 0)
    warns = int(counts.get(SEV_WARN) or 0)
    state = "all quiet" if not errors else "still here"
    subject = (f"CC Sync: {state} - {machines} computer(s), "
               f"{errors} problem(s)")
    body = [
        subject,
        "",
        "This is the daily proof that the CC Sync server is running and can "
        "still send you mail.",
        "IF THESE STOP ARRIVING, THE SERVER ITSELF IS DOWN. Nothing else "
        "tells you that: an alarm system that only speaks when something is "
        "wrong sounds exactly the same switched off.",
        "",
        f"Computers known to this server: {machines}",
        f"Problems open right now: {errors}",
        f"Things to look at: {warns}",
        "",
        "Turn this off on the dashboard: SETTINGS, ALERTS, DAILY 'STILL "
        "HERE' MESSAGE.",
    ]
    return subject, "\n".join(body) + "\n"


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
        # UX-16 (2026-09-03): "lane" is our word, not a reader's.
        return "no transfer ever reported"
    return ", ".join(f"{l.get('label') or l.get('lane')}={l.get('state')}" for l in lanes)


# ------------------------------------------------------------- the registry

Finding = dict            # {"subject", "diagnosis", "fix", "detail"}


def _f(subject: str, diagnosis: str, fix: str, detail: str = "",
       *, repeat: bool = True) -> Finding:
    """One finding. `repeat=False` (DDIAG-3, 2026-09-04) says "still true,
    still worth showing, but do not mail it again while it stays true" - the
    warn repeat rule on a finding an error kind produced. It is NOT the same
    as dropping the finding: a subject that leaves the scan is declared
    RECOVERED, and "this has cleared, no action is needed" about a computer
    that has been dead for a fortnight is a worse lie than the daily mail."""
    return {"subject": subject, "diagnosis": diagnosis, "fix": fix,
            "detail": detail, "repeat": repeat}


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
        from .api import YTDLP_META_PREFIX, build_editors_view

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
        # Which accounts are wired to the NAS on every machine they own
        # (CR-28). One fleet-wide read, on the Ctx rule that no check may go
        # back to the database per machine; the per-machine answer is the
        # entry's own `mode` and this is only the fallback for a machine that
        # predates v22 (see _check_engine_down).
        try:
            self.base_only: set[str] = db.base_only_editors(conn)
        except sqlite3.Error:
            self.base_only = set()
        # What the four optional mounts decided at boot (DDIAG-7's registry).
        # A module global rather than app state, because this runs on the
        # collector thread with no app object in hand.
        self.mounts: dict[str, tuple[str, str]] = mount_status.snapshot()
        # REL-6 / REL-3: the release channel's adoption picture, one read for
        # the two checks that ask about it. `channels: []` on a database that
        # has published nothing, which is not a fault.
        try:
            self.rollout: dict[str, Any] = db.rollout_status(conn, now=now)
        except sqlite3.Error:
            log.debug("alerts: could not read the rollout picture", exc_info=True)
            self.rollout = {"generated_at": now, "channels": []}
        # CYT-7: each computer's yt-dlp verdict, keyed "<editor>/<machine>",
        # as api._store_ytdlp_state filed it. Absent means that computer has
        # said nothing about yt-dlp, which must not read as "it is fine".
        self.ytdlp: dict[str, Any] = {}
        for row in _rows(conn, "SELECT key, value FROM meta WHERE key LIKE ?",
                         (f"{YTDLP_META_PREFIX}%",)):
            try:
                self.ytdlp[str(row["key"])[len(YTDLP_META_PREFIX):]] = json.loads(
                    row["value"])
            except (ValueError, TypeError):
                continue
        # YTWEB-2: the /ytdl stack's own health, in process, or None when
        # this dashboard is not serving it. Gathered ONCE for the five checks
        # that read it, and side-effect free by contract (no probe, no
        # database, no subprocess).
        self.ytdl: dict[str, Any] | None = _ytdl_health(self.mounts)
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


def _ytdl_health(mounts: Mapping[str, tuple[str, str]]) -> dict[str, Any] | None:
    """The /ytdl stack's health signals, or None when it is not serving.

    YTWEB-2 (2026-09-04). `ytdl.health_snapshot` is the published way in and
    it takes the app object, because the mount records its verdict on
    `app.state`. THERE IS NO APP HERE: the scan runs on the collector thread
    and from `/api/v1/health`'s handler, so the status comes from
    `mount_status` (the module-level registry DDIAG-7 added for exactly this
    class of reader) and is handed to that function on a stand-in carrying
    the one attribute it reads. The alternative was a second copy of its
    sys.modules lookup here, which would drift.

    None on any failure: "we could not ask" and "we asked and it is fine"
    are different answers, and every check below is written to say the first
    one by reporting nothing rather than by inventing a green.
    """
    status = (mounts.get("ytdl") or ("", ""))[0]
    if not status:
        return None
    try:
        from types import SimpleNamespace

        from . import ytdl as ytdl_mount

        return ytdl_mount.health_snapshot(
            SimpleNamespace(state=SimpleNamespace(ytdl_status=status)))
    except Exception:                                               # noqa: BLE001
        log.debug("alerts: could not read the ytdl health snapshot", exc_info=True)
        return None


def _sqlite_ro(path: Any) -> sqlite3.Connection | None:
    """A READ-ONLY connection to another component's database, or None.

    BROLL-2. `broll.db` and `client_shares.db` are not this dashboard's
    database and are held open read-write by the mounted app, so the two
    checks that read them open their own connection, ask one indexed
    question and close it. Read-only at the URI level rather than by
    convention: nothing in a diagnostic may write to a customer's index, and
    a b-roll checkout whose file is missing, locked or newer than this code
    is "could not ask", which the callers report as no finding.
    """
    try:
        if not path or not Path(str(path)).exists():
            return None
        conn = sqlite3.connect(f"file:{Path(str(path)).as_posix()}?mode=ro",
                               uri=True, timeout=1.0)
        conn.row_factory = sqlite3.Row
        return conn
    except (sqlite3.Error, OSError, ValueError):
        log.debug("alerts: could not open %s read-only", path, exc_info=True)
        return None


def _broll_paths() -> tuple[Any, Any]:
    """(broll.db, client_shares.db) from the mounted b-roll app's own config,
    or (None, None). `sys.modules` only: importing the b-roll tree inside a
    collector cycle on a site that does not have it is the one thing the
    mount's tri-state exists to avoid."""
    config = sys.modules.get("app.config")
    if config is None:
        return None, None
    try:
        return config.get_db_path(), config.get_data_root() / "client_shares.db"
    except Exception:                                               # noqa: BLE001
        return None, None


def _broll_mounted(ctx: "Ctx") -> bool:
    """Is the b-roll app serving here at all? Its checks are silent when it
    is not: a dashboard with no b-roll mount is a supported deployment, and
    the mount's own absence is reported once by `feature_not_mounted`."""
    return (ctx.mounts.get("broll") or ("", ""))[0] in ("mounted", "degraded")


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
        f"Syncing is stopped by an admin for every computer in the fleet. "
        f"Nothing is going up and nothing is coming down anywhere. It was set "
        f"{_age_words(halt.get('set_at'), ctx.now)} by "
        f"{halt.get('set_by') or 'an admin'}.",
        "On the dashboard: SYNC STATUS, then [ RELEASE THE HALT ] when "
        "whatever it was set for is over.",
        str(halt.get("reason") or ""))]


def _check_fleet_halt_expired(ctx: Ctx) -> list[Finding]:
    halt = ctx.halt
    if not (halt.get("active") and halt.get("expired")):
        return []
    return [_f(
        "the whole fleet",
        f"The fleet-wide stop set {_age_words(halt.get('set_at'), ctx.now)} has run "
        f"past its own expiry time, so syncing has started again on its own. "
        f"If the reason it was set is still true, nobody has been told.",
        "On the dashboard: SYNC STATUS, and either stop syncing again or "
        "confirm it is no longer needed.",
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
            f"{who} has stopped its own proxy download because the drive is nearly "
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
        # DDIAG-3 (2026-09-04): past the give-up this is said once and not
        # again while it stays true. A fortnight of silence is not an outage
        # anybody is going to act on this morning, and 21 identical mails
        # about a laptop that was retired is how an owner learns to filter
        # this sender. It stays OPEN on the page and becomes the standing
        # `machine_forgotten` notice on the home panel.
        given_up = age is not None and age > SILENT_GIVE_UP_DAYS * 86400
        out.append(_f(
            who,
            f"{who} has not been in touch since "
            f"{_age_words(e.get('received_at'), ctx.now)}. Everything this "
            f"dashboard shows for that computer is frozen at that moment, so a "
            f"green row there means nothing right now.",
            "Ask that editor to check the CC Sync tray icon is running and "
            "that the computer is on and online. If that computer is gone for "
            "good, open FLEET and press [ FORGET ] on its row so this stops.",
            f"last known state: {_lane_words(e)}",
            repeat=not given_up))
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


def _is_base_machine(ctx: Ctx, e: Mapping[str, Any]) -> bool:
    """This computer runs no sync lanes, so it has no sync engine to be down.

    The base rig works straight off the NAS share with `sync_enabled=false`
    and never starts lane C, so its Syncthing is RETIRED, not down -- but the
    supervisor recorded the incident the minute the engine went away and
    nothing ever polls it clear, so the record sits there for ever. The
    companion stopped saying it in the tray for this exact reason
    (app._why_not_syncing, syncthing_down, 2026-08-30); the dashboard kept
    saying it, and told the owner "the sync engine on alex/Creator_1 has been
    down for 6 days" about the machine the whole tree lives on.

    NOTHING IN THE REPORT SAYS sync_enabled. The companion sends no such
    field (the only `mode` it reads is its own config, never the payload), so
    the evidence here is the role the dashboard already holds:
    `machine_state.mode` per machine (v22, surfaced as entry["mode"]) with
    db.base_only_editors as the fallback for a machine that reported before
    v22. A REMOTE machine an editor has set sync_enabled=false on by hand
    still alerts, and that is accepted: nothing distinguishes it from a
    machine whose engine really did die, and for an editor's computer the
    dangerous direction is silence.
    """
    if str(e.get("mode") or "").strip().lower() == "base":
        return True
    return str(e.get("editor_username") or "") in ctx.base_only


def _check_engine_down(ctx: Ctx) -> list[Finding]:
    out = []
    for e in ctx.editors:
        # 2026-09-03, studio dashboard false alarms: a machine that runs no
        # lanes has no engine to be down (see _is_base_machine).
        if _is_base_machine(ctx, e):
            continue
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
            "Ask that editor to quit CC Sync from the tray and start it again. If it "
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
            f"A transfer on {who} is busy and nothing is moving")
        out.append(_f(
            who,
            f"{sentence}. A drive that has stopped answering reads exactly "
            f"like this, and the other transfers on that computer wait behind "
            f"it.",
            "Ask that editor to quit CC Sync from the tray and start it again, and to check "
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
                f"{_duration_words(age)}. Whatever that transfer carries is "
                f"not moving for that editor.",
                "Open the computer's row on the SYNC STATUS page and read the error, "
                "then ask that editor to quit CC Sync from the tray and start it again.",
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
            # UX-10 (usability sweep 2026-09-03): "(s)" is not a word, and
            # the count is right here.
            f"{count} shared folder{'' if count == 1 else 's'} on {who} "
            f"{'has' if count == 1 else 'have'} no ignore filter written "
            f"yet. Without it, that computer will carry camera originals in "
            f"both directions over the internet instead of proxies only.",
            "It normally writes itself on the next sync turn. If it is still "
            "here tomorrow, ask that editor to quit CC Sync from the tray and start it again.",
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
            # CR-88 route sweep (usability sweep 2026-09-03): Copy
            # diagnostics left the tray menu on 2026-08-27.
            f"Ask that editor to open {health.COMPANION_DIAGNOSTICS_PATH} on "
            f"that computer and send it to us.",
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
            f"written a report. The tray stays up and the transfers look normal, "
            f"which is why nobody notices.",
            # CR-88 route sweep (usability sweep 2026-09-03): the tray menu
            # has no Copy diagnostics since 2026-08-27.
            f"Ask that editor to open {health.COMPANION_DIAGNOSTICS_PATH} on "
            f"that computer and send it to us.",
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
            "Read the error on that computer's row on the SYNC STATUS page, then "
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
    """2026-09-03, studio dashboard false alarms: an EMPTY plan is not a plan.

    Fixed here rather than at the recording side on purpose.
    `db.record_enforce_plan` is DASH-3's dry-run view: the collector writes it
    once per cycle, unconditionally, so the steady state is a real and wanted
    record of `{"folders": [], "n_add": 0, "n_remove": 0}` that the home page
    reads to say "the last cycle had nothing to do". Not recording it would
    make "no plan yet" and "nothing to apply" the same absence. What is wrong
    is only this check reading "a record exists" as "a change is held", which
    stood a warn up on a dashboard with nothing whatsoever pending.
    """
    plan = ctx.collector.get("enforce_plan")
    if isinstance(plan, Mapping) and not (plan.get("n_add") or plan.get("n_remove")):
        return []
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

    Counts BUILDS newer than the one running, not a version-number difference:
    what matters is how many fixes that machine has not taken. Published here
    and offered by the vendor's feed both count (SYS-2, 2026-09-04) - a fix
    that exists and has not reached the machine is missing from it either way.
    """
    published: dict[str, set[tuple]] = {}
    for r in _rows(ctx.conn,
                   "SELECT platform, version FROM companion_packages "
                   "WHERE kind='companion' AND (retracted_at IS NULL OR retracted_at='')"):
        published.setdefault(str(r["platform"]), set()).add(db.version_tuple(r["version"]))
    # SYS-2 (2026-09-04): plus what the VENDOR is offering. Counting only what
    # this dashboard published makes the one case that can never self-heal
    # invisible: a companion build that names a newer `requires_dashboard` is
    # refused here, so it is never in `companion_packages`, so every machine is
    # "0 releases behind" while the whole fleet stops updating. The feed's
    # picture is a fact about the vendor's channel, not about this dashboard's
    # shelf, and an empty one means UNKNOWN (no check has run) rather than
    # "nothing on offer".
    try:
        for platform, versions in db.get_feed_offered(ctx.conn).items():
            for version in versions:
                tup = db.version_tuple(version)
                if tup:
                    published.setdefault(platform, set()).add(tup)
    except sqlite3.Error:
        log.debug("alerts: could not read what the vendor feed offers", exc_info=True)
    out = []
    for e in ctx.editors:
        version = db.version_tuple(e.get("companion_version"))
        if not version:
            continue
        newer = [v for v in published.get(e.get("platform") or "", set()) if v > version]
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
    # 2026-09-03, studio dashboard false alarms: the fleet's current build,
    # per platform, in ONE query for the whole check (the Ctx rule). A staged
    # row BELOW it lost its trial long ago -- 0.9.63 (windows) was still
    # naming ruskin's three crashes a week after 0.9.65 went current, and a
    # build that can never be handed to everybody cannot be a warning about
    # handing it to everybody. version_tuple, never a string compare: the
    # companion goes 0.9.9 -> 0.9.10.
    current: dict[str, tuple[int, ...]] = {}
    for row in _rows(ctx.conn,
                     "SELECT platform, version FROM companion_packages "
                     "WHERE kind='companion' AND is_current=1"):
        current[str(row["platform"])] = db.version_tuple(row["version"])
    for r in _rows(ctx.conn,
                   "SELECT platform, version FROM companion_packages "
                   "WHERE kind='companion' AND rollout='staged' "
                   "AND (retracted_at IS NULL OR retracted_at='')"):
        staged = db.version_tuple(r["version"])
        live = current.get(str(r["platform"]))
        # Unparseable on either side is "cannot tell", and cannot-tell keeps
        # the warning: silence is the direction this module exists to end.
        if staged and live and staged < live:
            continue
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


# ------------------------------------------------- the fleet job queue (DDIAG-2)
#
# The queue's own module says it: "THE FAILURE MODE OF A SCHEDULER IS
# INVISIBLE: a scheduler that quietly assigns nothing looks exactly like a
# fleet with nothing to do." Until 2026-09-04 the whole of it was diagnosed on
# /admin/jobs and nowhere else, and nothing on the home page links there.

def _queued_head(ctx: Ctx) -> Any:
    """The oldest QUEUED job, or None. `_rows`' rule: a database migrated by a
    build that predates the jobs table reads as an empty queue."""
    rows = _rows(ctx.conn,
                 "SELECT id, kind, created_at FROM jobs WHERE state='queued' "
                 "ORDER BY id ASC LIMIT 1")
    return rows[0] if rows else None


def _check_jobs_starved(ctx: Ctx) -> list[Finding]:
    """Work queued for six hours that no amount of waiting will place.

    `jobs.explain` is asked about ONE job, the oldest, and only once the six
    hours are up: it reads the whole fleet's capabilities, and the Ctx rule
    forbids doing that per row. The three reason codes below are the ones a
    person has to act on. `all_busy`, `idle_wait`, `fleet_cap` and
    `cooling_down` are deliberately NOT here: each of them is the scheduler
    working, and a queue that empties itself tonight is not a fault.
    """
    head = _queued_head(ctx)
    if head is None:
        return []
    age = _age(head["created_at"], ctx.now)
    if age is None or age < JOBS_STARVED_SECONDS:
        return []
    from . import jobs as jobs_mod

    info = jobs_mod.explain(ctx.conn, int(head["id"]), now=ctx.now) or {}
    code = str(info.get("reason_code") or "")
    meaning = {
        jobs_mod.REASON_NO_CAPABLE:
            "no computer in the fleet can do this kind of work",
        jobs_mod.REASON_NOT_ALLOWED:
            "every computer that could do it has this kind of work switched off",
        jobs_mod.REASON_HALTED:
            "syncing is stopped, and a computer with syncing stopped takes "
            "no jobs",
    }.get(code)
    if meaning is None:
        return []
    depth = _rows(ctx.conn, "SELECT COUNT(*) AS n FROM jobs WHERE state='queued'")
    queued = int(depth[0]["n"]) if depth else 1
    return [_f(
        "the fleet queue",
        f"{queued} job(s) have been waiting for the fleet to pick them up, the "
        f"oldest for {_duration_words(age)}, and {meaning}. Nothing is going to "
        f"take them: this queue will not empty by itself.",
        "Open Settings, JOBS: the WHY line under each job names the computer "
        "that would have to change.",
        f"job #{head['id']} kind={head['kind']} reason={code} queued={queued}")]


def _check_jobs_abandoned(ctx: Ctx) -> list[Finding]:
    """Jobs the fleet spent its whole retry budget on and gave up.

    One finding for the window, not one per job: a fleet that abandons twelve
    whisper jobs has one broken computer, and twelve messages about it is the
    shape MAX_FINDINGS_PER_KIND exists to prevent.
    """
    since = _iso_minus(ctx.now, JOBS_ABANDONED_HOURS * 3600)
    rows = _rows(ctx.conn,
                 "SELECT id, kind, last_error FROM jobs WHERE state='abandoned' "
                 "AND updated_at >= ? ORDER BY id DESC LIMIT 40", (since,))
    if not rows:
        return []
    kinds = ", ".join(sorted({str(r["kind"]) for r in rows}))
    first_error = next((str(r["last_error"]) for r in rows if r["last_error"]), "")
    ids = ",".join(str(r["id"]) for r in rows[:10])
    return [_f(
        "the fleet queue",
        f"The fleet gave up on {len(rows)} job(s) in the last day ({kinds}). "
        f"Whatever they were for did not happen: a proxy was not made, a "
        f"transcript was not written, and nothing anywhere else says so.",
        "Settings, JOBS, [ SHOW FINISHED ], then [ TRY AGAIN ] once the "
        "computer that failed it is fixed.",
        f"ids={ids} last_error={first_error[:120]}")]


def _check_jobs_pinned_no_executor(ctx: Ctx) -> list[Finding]:
    """A job pinned to this dashboard that this dashboard cannot run (DDIAG-6).

    Pinning is the last resort: the fleet spent its retry budget, so the job
    was handed to the dashboard's own Timeline Cards worker. That worker
    exists only while /cards is mounted, and the mount fails to `absent` for
    ordinary reasons an image update causes. A container that goes down
    mid-encode and comes back without it leaves rows nothing will ever return
    again, on no lease and with no expiry, while the jobs page still says the
    dashboard is running them.

    Two shapes, both read from the queue itself rather than from an executor
    object this thread cannot reach: pinned work with no Timeline Cards mount
    behind it at all, and a row this container marked as in hand whose
    heartbeat stopped an hour ago.
    """
    rows = _rows(ctx.conn,
                 "SELECT id, kind, claimed_machine, heartbeat_at, updated_at "
                 "FROM jobs WHERE state='pinned' LIMIT 40")
    if not rows:
        return []
    out: list[Finding] = []
    cards = (ctx.mounts.get("cards") or ("", ""))[0]
    if cards and cards != "mounted":
        out.append(_f(
            "the dashboard's own worker",
            f"{len(rows)} job(s) were pinned to this server because no computer "
            f"in the fleet could finish them, and the Timeline Cards worker "
            f"that was going to run them is not loaded here any more. They "
            f"will wait for ever, and the jobs page says they are in hand.",
            "Check the container's bind mounts and restart the dashboard "
            "(docs/DOCKER.md), then Settings, JOBS to see them move.",
            f"cards mount={cards} pinned={len(rows)}"))
    stale = [r for r in rows
             if str(r["claimed_machine"] or "")
             and (_age(r["heartbeat_at"] or r["updated_at"], ctx.now) or 0.0)
             > PINNED_STALE_SECONDS]
    if stale:
        ids = ",".join(str(r["id"]) for r in stale[:10])
        out.append(_f(
            "a stranded pinned job",
            f"{len(stale)} job(s) are marked as being run by this server right "
            f"now, and nothing has reported progress on them for over an hour. "
            f"That is what a container restarted mid-encode leaves behind, and "
            f"nothing releases them on its own.",
            "Settings, JOBS, then [ CANCEL ] on each one and queue it again.",
            f"ids={ids}"))
    return out


# ----------------------------------------------------- the channel (REL-3/6/13)

def _check_upgrade_refused(ctx: Ctx) -> list[Finding]:
    """A computer that REFUSES the offer, rather than failing to install it.

    REL-3. A refusal happens at receipt (a signature this build will not
    trust, a version below its downgrade floor, plain HTTP to a public host),
    so no attempt is ever made: `upgrade_attempts` stays 0 and the machine
    renders identically to one that has simply not reported yet. It is
    strictly worse than a merely outdated computer, because no button on the
    page can fix it.
    """
    out = []
    for r in _rows(ctx.conn,
                   "SELECT editor_username, machine, upgrade_refused_version, "
                   "upgrade_refused_reason, upgrade_refused_at FROM machine_state "
                   "WHERE upgrade_refused_version IS NOT NULL "
                   "AND upgrade_refused_version != '' LIMIT 40"):
        who = ctx.name(f"{r['editor_username']}/{r['machine']}")
        reason = str(r["upgrade_refused_reason"] or "it did not say why")
        out.append(_f(
            who,
            f"{who} is turning down every update it is offered. It refused "
            f"{r['upgrade_refused_version']} "
            f"({_age_words(r['upgrade_refused_at'], ctx.now)}) and gave this "
            f"reason: {reason}. It never downloaded anything, so it will keep "
            f"refusing, and pressing the update button on this dashboard "
            f"cannot change that.",
            "Settings, PACKAGES: publish a build that computer will accept, or "
            "install it there by hand from the INSTALLER link. [ UPDATE NOW ] "
            "cannot fix a refusal.",
            f"refused={r['upgrade_refused_version']} "
            f"at={r['upgrade_refused_at']}"))
    return out


def _check_rollout_stalled(ctx: Ctx) -> list[Finding]:
    """A build that has been current for two days and is not being taken.

    REL-6. `versions_behind` needs a computer to be THREE published builds
    behind, so a fleet that stopped updating after one release is silent for
    months. This asks the other question: not "how far behind is that
    computer" but "did the thing we shipped on Tuesday actually arrive".

    A channel whose `made_current_at` is NULL is a build made current before
    the column existed: the answer is "cannot tell", and it is silence here
    rather than a rollout dated to a moment nobody was ever offered anything.
    Only computers that have REPORTED inside the window count: one that is
    switched off is not refusing an update, it is switched off, and
    `machine_silent` is the kind that owns that.
    """
    out = []
    for channel in ctx.rollout.get("channels") or []:
        made = channel.get("made_current_at")
        age = _age(made, ctx.now) if made else None
        if age is None or age < ROLLOUT_STALLED_SECONDS:
            continue
        live = [b for b in channel.get("behind") or []
                if (_age(b.get("last_seen"), ctx.now)
                    or (ROLLOUT_STALLED_SECONDS + 1)) <= ROLLOUT_STALLED_SECONDS]
        if not live:
            continue
        names = ", ".join(f"{b['editor']}/{b['machine']} on {b['version']}"
                          for b in live[:6])
        out.append(_f(
            f"{channel.get('platform') or '?'} companion "
            f"{channel.get('current_version')}",
            f"{channel.get('current_version')} has been the current CC Sync "
            f"build for {channel.get('platform')} computers since "
            f"{_age_words(made, ctx.now)}, and "
            f"{channel.get('machines_on_current')} of "
            f"{channel.get('machines_total')} have taken it. {len(live)} "
            f"computer(s) have reported since then and are still on an older "
            f"build: {names}.",
            "Settings, PACKAGES, then [ UPDATE NOW ] on each computer that is "
            "behind. One that is refusing the offer is reported separately.",
            f"platform={channel.get('platform')} "
            f"reverts={channel.get('reverts')} "
            f"failed_attempts={channel.get('failed_attempts')}"))
    return out


def _check_platform_channel_stale(ctx: Ctx) -> list[Finding]:
    """One platform's build left behind by the other's (REL-13).

    A macOS bundle cannot be cross-built from Windows, so every ship prints a
    yellow advisory naming the two Mac commands and then exits 0. That signal
    exists twice per ship, in a terminal's scrollback, and Mac builds have
    been owed across many ships (one Mac sat on 0.9.2 for weeks). Nothing
    durable recorded it, so nothing reminded anybody on a day they were not
    shipping.

    Two measures, because the first one only works on builds this dashboard
    stamped: DAYS since each channel was made current, and, when either stamp
    is missing, how many builds the leading platform has published that the
    lagging one's current version is behind.
    """
    channels = [c for c in (ctx.rollout.get("channels") or [])
                if c.get("current_version")]
    if len(channels) < 2:
        return []
    published: dict[str, list[tuple]] = {}
    for r in _rows(ctx.conn,
                   "SELECT platform, version FROM companion_packages "
                   "WHERE kind='companion' "
                   "AND (retracted_at IS NULL OR retracted_at='')"):
        tup = db.version_tuple(r["version"])
        if tup:
            published.setdefault(str(r["platform"]), []).append(tup)
    leader = max(channels,
                 key=lambda c: db.version_tuple(c["current_version"]) or ())
    out = []
    for channel in channels:
        if channel is leader:
            continue
        mine = db.version_tuple(channel["current_version"]) or ()
        theirs = db.version_tuple(leader["current_version"]) or ()
        if not mine or not theirs or mine >= theirs:
            continue
        behind = len([v for v in published.get(str(leader.get("platform")), [])
                      if v > mine])
        stamp_gap = None
        if channel.get("made_current_at") and leader.get("made_current_at"):
            mine_age = _age(channel["made_current_at"], ctx.now)
            their_age = _age(leader["made_current_at"], ctx.now)
            if mine_age is not None and their_age is not None:
                stamp_gap = mine_age - their_age
        if stamp_gap is not None:
            if stamp_gap < PLATFORM_CHANNEL_STALE_SECONDS:
                continue
            evidence = (f"it was published {_duration_words(stamp_gap)} before "
                        f"the {leader.get('platform')} one")
        else:
            if behind <= PLATFORM_CHANNEL_STALE_BUILDS:
                continue
            evidence = f"it is {behind} builds behind"
        out.append(_f(
            f"the {channel.get('platform')} channel",
            f"The current CC Sync build for {channel.get('platform')} "
            f"computers is {channel['current_version']} and {evidence}. "
            f"{leader.get('platform')} computers are on "
            f"{leader['current_version']}. Every fix since then is missing on "
            f"that half of the fleet, and nothing will offer it to them until "
            f"somebody builds it.",
            "On a Mac, in the repo: git pull && ./tools/release_macos.sh "
            "--publish --make-current, then ./tools/build_onboard_macos.sh "
            "--publish --make-current. PyInstaller cannot build a macOS "
            "bundle on Windows, so no ship from a Windows computer can do "
            "this.",
            f"{channel.get('platform')}={channel['current_version']} "
            f"{leader.get('platform')}={leader['current_version']} "
            f"behind={behind}"))
    return out


# ------------------------------------------- each computer's own tools (CYT-7)

def _check_ytdlp_stale(ctx: Ctx) -> list[Finding]:
    """A computer whose yt-dlp is old and could not update itself.

    CYT-7. The max-age rule publishes this verdict with `ok=True` (the binary
    can still very probably download), so `capabilities()` never surfaced it,
    the browser toast never fired and the message went to one INFO line a day
    in that editor's companion.log. Only computers the fleet view still has
    are looked at: a stored verdict for a forgotten computer alarms nobody.
    """
    out = []
    for e in ctx.editors:
        record = ctx.ytdlp.get(_who(e)) or {}
        if not record.get("stale"):
            continue
        who = ctx.name(_who(e))
        message = str(record.get("message") or "").strip() or (
            "YouTube breaks these tools deliberately, so downloads on that "
            "computer will start failing.")
        out.append(_f(
            who,
            f"The YouTube downloader on {who} is out of date and could not "
            f"update itself. {message}",
            "Ask that editor to quit CC Sync from the tray and start it again "
            "while they are online: it updates the downloader at startup. If "
            "it keeps happening, send us their companion log.",
            f"version={record.get('version')} age_days={record.get('age_days')} "
            f"checked={record.get('checked_at')}"))
    return out


def _check_ytdlp_failed(ctx: Ctx) -> list[Finding]:
    """No usable yt-dlp at all on that computer: a different alarm from stale.

    The companion keeps `failed` and `stale` apart on purpose (one is a
    binary that is old, the other is a binary that is not there), and folding
    them here would cost the difference between "it will start failing" and
    "it fails now".
    """
    out = []
    for e in ctx.editors:
        record = ctx.ytdlp.get(_who(e)) or {}
        if str(record.get("action") or "") != "failed":
            continue
        who = ctx.name(_who(e))
        message = str(record.get("message") or "").strip() or (
            "The download tool could not be installed or updated there.")
        out.append(_f(
            who,
            f"{who} has no working YouTube downloader. {message} Every YouTube "
            f"download that computer is asked to do will fail, and the request "
            f"goes back to the server to do instead.",
            "Ask that editor to quit CC Sync from the tray and start it again "
            "while they are online. If it still fails, that computer's "
            "antivirus or its network is blocking the download tool.",
            f"version={record.get('version')} "
            f"checked={record.get('checked_at')}"))
    return out


def _check_loopback_down(ctx: Ctx) -> list[Finding]:
    """"Send to Resolve" cannot work on that computer (CMEDIA-3).

    The 8899 loopback is the one companion service a WEB PAGE depends on.
    When the port is held (the absorbed standalone BRoll Companion, a
    leftover process after a crash) the companion logged one warning and ran
    happily for ever with no listener, and what the editor saw was the b-roll
    page saying the tray app is not running: wrong in its first clause, and
    it sends them to restart something that is already running.

    `enabled` false is a choice, not a fault, and all-NULL is a companion too
    old to say. Only "the feature is on and the port is not ours" is a
    finding.
    """
    out = []
    for e in ctx.editors:
        g = ctx.guard(e)
        if not g.get("loopback_enabled") or g.get("loopback_bound") is None:
            continue
        if g.get("loopback_bound"):
            continue
        who = ctx.name(_who(e))
        error = str(g.get("loopback_error") or "the port could not be taken")
        out.append(_f(
            who,
            f"The b-roll and music pages cannot send anything to Resolve on "
            f"{who}: the port they talk to it on is held by something else, "
            f"since {_age_words(g.get('loopback_since'), ctx.now)}. The page "
            f"tells that editor CC Sync is not running, which is not what is "
            f"wrong.",
            "Quit whatever holds port 8899 on that computer (an old BRoll "
            "Companion, a leftover process), then restart the CC Sync tray.",
            f"port={g.get('loopback_port')} error={error[:200]}"))
    return out


# ----------------------------------------------- the YouTube stack (YTWEB-2/5)

def _check_ytdl_worker_dead(ctx: Ctx) -> list[Finding]:
    """The download worker thread on this server is not running.

    Nothing queued will ever start, and the page shows jobs sitting at
    "waiting" with no error on any of them.
    """
    snap = ctx.ytdl
    if snap is None or snap.get("worker_alive") is not False:
        return []
    return [_f(
        "the YouTube downloader",
        "The download worker on this server is not running, so every YouTube "
        "download anybody starts will sit in the queue for ever with no error "
        "on it.",
        "Restart the ccsync container on the NAS, then open the YOUTUBE page "
        "and check the health strip is green.",
        "worker_alive=false")]


def _check_ytdl_downloads_failing(ctx: Ctx) -> list[Finding]:
    """The last real download failed AND the canary agrees.

    Two signals, because one is not evidence: a single failed download is
    usually one bad video (private, age-gated, geo-blocked). The canary is a
    known-good clip this server extracts on a timer, so a canary that failed
    too is the downloader itself being broken. With no canary result there is
    no finding: crying wolf on one bad URL is how a health strip stops being
    read.
    """
    snap = ctx.ytdl
    if snap is None:
        return []
    last = snap.get("last_download")
    if not isinstance(last, Mapping) or last.get("ok") is not False:
        return []
    canary = snap.get("canary")
    latest = canary.get("last") if isinstance(canary, Mapping) else None
    if not isinstance(latest, Mapping) or latest.get("ok") is not False:
        return []
    return [_f(
        "the YouTube downloader",
        "Downloading from YouTube is failing on this server. The last real "
        "download failed and so did the test clip this server fetches by "
        "itself, which means it is the downloader rather than one bad video. "
        "YouTube changes its site to break these tools deliberately.",
        "Settings, then check for a dashboard update: a newer build carries a "
        "newer download tool. Until then, editors can download on their own "
        "computer from the YOUTUBE page.",
        f"path={last.get('path')} error={str(last.get('error') or '')[:160]}")]


def _check_ytdl_pot_provider(ctx: Ctx) -> list[Finding]:
    """A PO-token sidecar that is configured and not answering.

    ONLY `unreachable`. `unconfigured` is the shipped compose's normal state
    (the pip-installed plugin is the path this deployment actually uses) and
    `unknown` is "not asked yet"; alerting on either would be an amber pip
    nobody can clear, which is the failure this module exists to stop
    repeating.
    """
    snap = ctx.ytdl
    if snap is None or str(snap.get("pot_provider") or "") != "unreachable":
        return []
    return [_f(
        "the YouTube downloader",
        "The helper this server uses to prove to YouTube that it is not a bot "
        "is configured and is not answering. Downloads will be slow, and some "
        "will come back empty.",
        "Check the PO-token helper named by YTDL_POT_BASE_URL is running, or "
        "unset it (docs/DOCKER.md); this server then falls back to the plugin "
        "it installs at boot.",
        "pot_provider=unreachable")]


def _check_ytdl_plugin_install(ctx: Ctx) -> list[Finding]:
    """The anti-bot plugin's BOOT INSTALL failed (YTWEB-5).

    The real PO-token path on the shipped compose is a pip-installed plugin
    on PYTHONPATH, not the sidecar `pot_provider` reports on. Its install
    failed for days twice (CR-73: DNS not up in the first seconds; CR-84: a
    read-only /venv), and the entire evidence was four WARNING lines in a
    container log: what an editor saw was 1.8 MiB/s downloads and "the file
    is empty".
    """
    snap = ctx.ytdl
    if snap is None:
        return []
    state = snap.get("plugin_install")
    if not isinstance(state, Mapping) or str(state.get("state") or "") != "failed":
        return []
    return [_f(
        "the YouTube downloader",
        f"The anti-bot plugin this server needs for YouTube did not install "
        f"when the container started, after {state.get('attempts') or 0} "
        f"attempt(s). Downloads will crawl and some will arrive empty, and "
        f"nothing on the download page says why.",
        "Read the container log on the NAS for the plugin install lines, then "
        "restart the ccsync container once the network is up (docs/DOCKER.md).",
        f"error={str(state.get('error') or '')[:200]} at={state.get('at')}")]


def _check_ytdl_stale(ctx: Ctx) -> list[Finding]:
    """This server's own yt-dlp is past its shelf life.

    The same rule as CYT-7's per computer, on the copy in this container: it
    is the one signal that would have shown CR-80 and CR-83 coming, and in
    both the stale version was reported by an editor who could not download.
    """
    snap = ctx.ytdl
    if snap is None or not snap.get("yt_dlp_stale"):
        return []
    return [_f(
        "the YouTube downloader",
        f"The YouTube download tool on this server is "
        f"{snap.get('yt_dlp_age_days')} days old. YouTube breaks these tools "
        f"deliberately, so downloads here will start failing, and the newer "
        f"one arrives with a dashboard update.",
        "Settings, then [ CHECK NOW ] under the dashboard update panel, and "
        "install the build it offers.",
        f"version={snap.get('yt_dlp_version')} "
        f"age_days={snap.get('yt_dlp_age_days')}")]


# --------------------------------------------------------- b-roll (BROLL-2)

def _check_broll_batch_stuck(ctx: Ctx) -> list[Finding]:
    """An ingest batch nobody has worked on for a day.

    Read out of `broll.db` on its own read-only connection: it is another
    component's database and the mounted app holds it open. Anything that
    cannot be read is no finding rather than a fault here, because the b-roll
    mount's own absence is reported once, by `feature_not_mounted`.
    """
    if not _broll_mounted(ctx):
        return []
    path, _shares = _broll_paths()
    conn = _sqlite_ro(path)
    if conn is None:
        return []
    try:
        rows = list(conn.execute(
            "SELECT uid, editor, machine, share, state, n_items, n_done, "
            "       created_at, last_heartbeat_at "
            "  FROM ingest_batches "
            " WHERE state IN ('queued','claimed','running') LIMIT 40"))
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        age = _age(r["last_heartbeat_at"] or r["created_at"], ctx.now)
        if age is None or age < BROLL_BATCH_STUCK_SECONDS:
            continue
        who = f"{r['editor']}/{r['machine'] or 'no computer'}"
        out.append(_f(
            f"b-roll batch {r['share']}",
            f"A b-roll indexing job for {r['share']} has not moved for "
            f"{_duration_words(age)} ({r['n_done'] or 0} of {r['n_items'] or 0} "
            f"clips done, started by {who}). Those clips are not searchable "
            f"and nothing is working on them.",
            "Ask that editor to reopen the b-roll ingest panel on that "
            "computer, or cancel the batch on the B-ROLL page.",
            f"uid={r['uid']} state={r['state']}"))
    return out


def _check_broll_share_expiring(ctx: Ctx) -> list[Finding]:
    """A client link that stops working within the week.

    `client_shares.db`, deliberately NOT tables inside `broll.db`: publishing
    the index must never be able to take a customer's client links with it,
    and this check reads the ledger where it lives.
    """
    if not _broll_mounted(ctx):
        return []
    _index, path = _broll_paths()
    conn = _sqlite_ro(path)
    if conn is None:
        return []
    try:
        rows = list(conn.execute(
            "SELECT id, title, expires_at FROM client_folders "
            " WHERE revoked_at IS NULL AND expires_at IS NOT NULL "
            "   AND expires_at != '' LIMIT 40"))
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        # `_age` is now minus then, so an expiry still in the future is
        # NEGATIVE. Already expired (>= 0) is not a warning: the link is gone
        # and the client has met it.
        left = _age(r["expires_at"], ctx.now)
        if left is None or left > 0 or -left > BROLL_SHARE_EXPIRY_SECONDS:
            continue
        title = str(r["title"] or "a client folder")
        out.append(_f(
            f"client link: {title}",
            f"The client link for {title} stops working in "
            f"{_duration_words(left)}. Whoever you sent it to will get a page "
            f"saying the link has expired, and nothing tells them who to ask.",
            "Open B-ROLL, CLIENT FOLDERS, and either extend the expiry date or "
            "let it lapse on purpose.",
            f"expires_at={r['expires_at']}"))
    return out


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
            "Open that computer's row on the SYNC STATUS page and press [ ASK WHY ], "
            "then send us the diagnostics it returns.",
            f"status={e.get('status')} reason={e.get('status_reason') or ''}"))
    return out


# The registry. ORDER MATTERS in exactly one way: `red_unexplained` is last,
# because it reports only what the specific kinds above it did not name.
ALERT_KINDS: tuple[AlertKind, ...] = (
    AlertKind("breaker_tripped", SEV_ERROR, "proxy download stopped itself",
              "a computer's proxy download brake", _check_breaker),
    AlertKind("fleet_halt", SEV_WARN, "syncing is stopped for the whole fleet",
              "the fleet-wide stop", _check_fleet_halt),
    AlertKind("fleet_halt_expired", SEV_WARN, "a fleet-wide stop expired by itself",
              "a fleet-wide stop past its expiry", _check_fleet_halt_expired),
    AlertKind("disk_park", SEV_ERROR, "a computer stopped its own downloads for space",
              "a computer that stopped itself below its disk floor",
              _check_disk_park),
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
    AlertKind("lane_stalled", SEV_ERROR, "a sync transfer is stuck",
              "transfers busy with nothing moving", _check_lane_stalled),
    AlertKind("lane_error", SEV_ERROR, "a sync transfer has been failing",
              "transfers in error for an hour", _check_lane_error),
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
    # DDIAG-2 / DDIAG-6 (2026-09-04): the fleet job queue, which had no entry
    # in any diagnosis channel at all.
    AlertKind("jobs_starved", SEV_WARN, "work is queued and nobody is taking it",
              "the fleet job queue", _check_jobs_starved),
    AlertKind("jobs_abandoned", SEV_WARN, "the fleet gave up on some work",
              "jobs the fleet abandoned", _check_jobs_abandoned),
    AlertKind("jobs_pinned_no_executor", SEV_ERROR,
              "a job is pinned here and nothing here can run it",
              "pinned jobs against this dashboard's own worker",
              _check_jobs_pinned_no_executor),
    # REL-3 / REL-6 / REL-13 (2026-09-04): did the build we shipped actually
    # arrive, and is one of the two platforms being left behind.
    AlertKind("upgrade_refused", SEV_ERROR, "a computer is refusing every update",
              "computers refusing the offer outright", _check_upgrade_refused),
    AlertKind("rollout_stalled", SEV_WARN, "a new build is not being taken",
              "adoption of the current build", _check_rollout_stalled),
    AlertKind("platform_channel_stale", SEV_WARN, "one platform's build is behind",
              "the two platforms' channels against each other",
              _check_platform_channel_stale),
    # CYT-7 / CMEDIA-3: the tools on each editor's own computer.
    AlertKind("ytdlp_stale", SEV_WARN, "a computer's YouTube downloader is old",
              "each computer's yt-dlp", _check_ytdlp_stale),
    AlertKind("ytdlp_failed", SEV_ERROR,
              "a computer has no working YouTube downloader",
              "computers with no usable yt-dlp", _check_ytdlp_failed),
    AlertKind("loopback_down", SEV_WARN,
              "Send to Resolve cannot work on a computer",
              "the 8899 loopback on each computer", _check_loopback_down),
    # YTWEB-2 / YTWEB-5: the /ytdl stack on this server.
    AlertKind("ytdl_worker_dead", SEV_ERROR, "the YouTube downloader is not running",
              "the download worker on this server", _check_ytdl_worker_dead),
    AlertKind("ytdl_downloads_failing", SEV_WARN, "YouTube downloads are failing",
              "downloads on this server", _check_ytdl_downloads_failing),
    AlertKind("ytdl_pot_provider_unreachable", SEV_WARN,
              "the YouTube anti-bot helper is not answering",
              "the PO-token sidecar", _check_ytdl_pot_provider),
    AlertKind("ytdl_plugin_install_failed", SEV_WARN,
              "the YouTube anti-bot plugin did not install",
              "the plugin install at boot", _check_ytdl_plugin_install),
    AlertKind("ytdl_stale", SEV_WARN, "this server's YouTube downloader is old",
              "yt-dlp on this server", _check_ytdl_stale),
    # BROLL-2: the b-roll platform, which had one row in this registry and it
    # was about the SYNC drop folder.
    AlertKind("broll_batch_stuck", SEV_WARN, "a b-roll indexing job has stopped",
              "b-roll ingest batches", _check_broll_batch_stuck),
    AlertKind("broll_share_expiring", SEV_WARN, "a client link is about to expire",
              "client links near their expiry", _check_broll_share_expiring),
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
    lines = ["BYTES MOVED (per transfer, since it last reset)"]
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
        lines.append(f"  {version}: {len(rows)} of {total} "
                     f"computer{'' if total == 1 else 's'}")
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

    # 3c. The fleet queue, in one line (DDIAG-2, 2026-09-04). Printed every
    #     week including "0 queued, 0 running, 0 abandoned": the queue is
    #     invisible on every other page an owner opens, and a line that
    #     appeared only on bad weeks would make its absence read as good news.
    #     `_rows`' rule, so a database with no jobs table prints nothing at
    #     all rather than a made-up zero.
    queue = _rows(conn, "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state")
    if queue:
        counts = {str(r["state"]): int(r["n"]) for r in queue}
        abandoned = _rows(
            conn, "SELECT COUNT(*) AS n FROM jobs WHERE state='abandoned' "
                  "AND updated_at >= ?", (week_ago,))
        lines.append(
            f"JOBS: {counts.get('queued', 0)} queued, "
            f"{counts.get('running', 0)} running, "
            f"{int(abandoned[0]['n']) if abandoned else 0} abandoned this week")
        lines.append("")

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
    # bug-hunt-2026-09-03 dash-collector-1: a check that CRASHED files its
    # finding under CHECK_FAILED.kind with the failing kind's name as the
    # subject, never under its own kind - so testing by_kind alone printed
    # `ok - <what>` for a kind this report separately lists as unchecked.
    # `deliver` already subtracts the same subject set; the two halves of the
    # module have to agree. The denominator stays len(ALERT_KINDS) so the
    # report keeps stating how many kinds exist.
    _failed_subjects = {
        str(f.get("subject") or "") for f in (by_kind.get(CHECK_FAILED.kind) or [])
    }
    clean = [
        k for k in ALERT_KINDS
        if not by_kind.get(k.kind) and k.kind not in _failed_subjects
    ]
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


def _tls_context(verify: bool) -> ssl.SSLContext:
    """The context STARTTLS is negotiated with (dash-collector-3).

    Verifying by default. The opt-out is a stored setting an admin chose, so
    the page can say a site is running unverified; it is never reached by
    falling back after a verification failure.
    """
    if verify:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


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
    verify_tls = (values.get("alerts_smtp_verify_tls") or "1") == "1"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text)

    try:
        with _smtp_class()(host, port, timeout=SEND_TIMEOUT_SECONDS) as client:
            if use_tls:
                # bug-hunt-2026-09-03 dash-collector-3: `starttls()` with no
                # context builds ssl._create_stdlib_context(), which verifies
                # NOTHING (check_hostname False, CERT_NONE). Anyone who can
                # answer on this host and port then receives client.login()
                # with the stored SMTP password and a body naming every
                # editor, machine and fault. The webhook path already refuses
                # a plain-http URL at save AND at send time; the mail path is
                # held to the same standard.
                client.starttls(context=_tls_context(verify_tls))
            if user:
                client.login(user, password)
            client.send_message(message)
    except ssl.SSLCertVerificationError as exc:
        # Named, not silently downgraded: a self-signed internal relay is a
        # readable refusal with a setting to turn off, never an unverified
        # connection everyone else also gets.
        raise AlertError(
            f"the certificate {host} presented could not be verified "
            f"({str(getattr(exc, 'verify_message', '') or exc)[:120]}). "
            "If this is your own mail server with its own certificate, turn "
            "off 'Verify the mail server's certificate' on this page."
        ) from None
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
        db.record_alert(conn, kind, key, "", False, NO_SINK_DETAIL, now)
        return {"ok": False, "sink": sink, "sent_to": "",
                "detail": NO_SINK_DETAIL, "deduped": False}
    try:
        if sink == SINK_WEBHOOK:
            url = (values.get("alerts_webhook_url") or "").strip()
            # bug-hunt-2026-09-03 dash-collector-5: the ORIGIN goes in the
            # ledger, never the full URL. `alert_log.sent_to` is rendered on
            # the Alerts page and travels in every database backup, and a
            # Slack/Teams/Discord URL's path is the credential.
            sent_to = url_origin(url) or "webhook"
            detail = _send_webhook(url, subject, text)
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


def _send_committed(conn: sqlite3.Connection, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """send(), with the write transaction closed either side of it.

    THE NETWORK CALL MUST NOT SIT UNDER THE WRITE LOCK (2026-09-03 database is
    locked, api_report held the lock). send() records the attempt in
    alert_log, so a run of alerts held one open transaction across an SMTP
    conversation or a webhook POST -- up to SEND_TIMEOUT_SECONDS each, against
    a host that may simply not answer -- while every other writer on this
    database waited. Dormant while the sink is `none`, which is the vendor
    default; it was a landmine for the first site that configured one.

    Committing after each send is also what makes an alert_log row
    individually durable: the record of "we told somebody" now lands with the
    telling, not at the end of the cycle.
    """
    conn.commit()
    try:
        return send(conn, *args, **kwargs)
    finally:
        conn.commit()


def deliver(
    conn: sqlite3.Connection, settings: Any, findings: list[dict[str, Any]], now: str,
    *, budget_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Send what is new, re-send what is still an error, say what recovered.

    The repeat rule is the SEVERITY's: an "error" repeats once a day for as
    long as it is true, because an outage nobody acted on must not go quiet; a
    "warn" is said once and not again until it has cleared and come back.

    DDIAG-1 (2026-09-04): the pass stops sending once `budget_seconds` is
    spent and reports how many it left (`undelivered`). Every one of those is
    still an OPEN condition with no `alert_log` row, so the next cycle picks it
    up unchanged - the alternative was a run of 20 s timeouts long enough for
    the collector watchdog to replace the container mid-pass, which loses the
    same messages AND takes the dashboard with them. `clock` is injected so a
    test can spend the budget without waiting for it.
    """
    sent = failed = recovered = undelivered = 0
    # Read at CALL time, never bound as a default argument: the module
    # constant is what an operator or a test changes, and a default captured
    # at import cannot be changed by either.
    budget = ALERT_CYCLE_BUDGET_SECONDS if budget_seconds is None else budget_seconds
    deadline = clock() + max(0.0, float(budget))
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        kind = str(finding["kind"])
        subject = str(finding["subject"])
        seen.add((kind, subject))
        severity = finding.get("severity", SEV_WARN)
        was_open = _is_open(conn, kind, subject)
        # DDIAG-3: a finding may opt OUT of its kind's daily repeat while
        # staying open. Nothing may opt in: the repeat rule is the severity's.
        if was_open and (severity != SEV_ERROR or not finding.get("repeat", True)):
            continue
        if clock() >= deadline:
            # Left for the next pass, and NOT recorded: an alert_log row is
            # what "we told somebody" means, and dedup reads any row.
            undelivered += 1
            continue
        mail_subject, text = compose_alert(kind, subject, _finding_body(finding))
        result = _send_committed(conn, settings, mail_subject, text, kind=kind,
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
        if clock() >= deadline:
            # A recovery left unsent stays OPEN in the ledger, so it is said
            # next pass. Losing the good news for ten minutes is the cheap
            # half of this budget; the expensive half is above.
            undelivered += 1
            continue
        mail_subject, text = compose_recovered(kind, subject)
        result = _send_committed(conn, settings, mail_subject, text,
                                 kind=kind + RECOVERED_SUFFIX, dedup_subject=subject,
                                 now=now, dedup=False)
        recovered += 1
        failed += 0 if result["ok"] else 1
    return {"sent": sent, "failed": failed, "recovered": recovered,
            "undelivered": undelivered}


def _open_subjects(
    conn: sqlite3.Connection, kinds: set[str],
) -> list[tuple[str, str]]:
    """Every (kind, subject) currently in an alerted state, for the kinds
    given. One query over the ledger rather than one per subject.

    bug-hunt-2026-09-03 dash-collector-4: this used to page the most recent
    500 rows (`db.fetch_alerts`'s hard cap, which a caller cannot widen). A
    WARN writes ONE row and is then silent for as long as `_is_open` says it
    is open, so its row ages out of that window while error kinds write one a
    day - and once it had scrolled out, no `<kind>.ok` was ever recorded, so
    `_is_open` answered True for ever and that subject's warn was permanently
    muted. Grouping is recency-independent; `ix_alert_log_kind` covers
    (kind, subject, id). Raising the cap would only move the cliff.
    """
    if not kinds:
        return []
    names = sorted(kinds)
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        f"SELECT kind, subject FROM alert_log WHERE kind IN ({placeholders}) "
        "GROUP BY kind, subject",
        names,
    ).fetchall()
    subjects = {(str(r["kind"]), str(r["subject"])) for r in rows}
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
    _record_delivery_budget(conn, result, now)
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
    heartbeat = False
    if heartbeat_due(conn, now):
        # DDIAG-17 (2026-09-04). Sent through `send` like anything else, so a
        # failure is recorded and shows on WHAT WAS SENT; dedup OFF because
        # `heartbeat_due` IS the schedule, exactly as it is for the weekly
        # report. It is not a registry kind, so it can never count as a
        # problem, be recovered, or reach CURRENTLY OPEN - and it is NOT the
        # weekly report doubling as one: a proof of life a week wide leaves
        # six days in which "no mail" means nothing at all.
        subject, text = compose_heartbeat(conn, counts)
        outcome = send(conn, settings, subject, text, kind=KIND_HEARTBEAT,
                       dedup_subject="heartbeat", now=now, dedup=False)
        heartbeat = bool(outcome["ok"])
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
    sink = get_settings(conn).get("alerts_sink") or SINK_NONE
    if result.get("undelivered"):
        # DDIAG-1: the number that says the relay is slow, not that the fleet
        # is broken.
        note = (f"{result['sent']} of {result['sent'] + result['undelivered']} "
                f"alert(s) sent this pass; the alert channel is slow")
    elif result["failed"] and sink == SINK_NONE:
        # DDIAG-16 (2026-09-04): with no sink this is not a fault, it is the
        # setting. "could not be delivered" on the collector health panel read
        # as a broken mail server on a site that had simply never configured
        # one, which is the wrong thing to go looking for.
        note = (f"{result['failed']} alert(s) were written down here and "
                f"nobody was told: no alert channel is set up")
    elif result["failed"]:
        note = f"{result['failed']} alert(s) could not be delivered"
    elif counts.get(SEV_ERROR):
        note = f"{counts[SEV_ERROR]} problem(s) open"
    return {**result, "weekly": weekly, "heartbeat": heartbeat,
            "open": counts, "note": note, "sink": sink}


def _record_delivery_budget(
    conn: sqlite3.Connection, result: dict[str, Any], now: str,
) -> None:
    """File (or close) the "this pass ran out of time" notice (DDIAG-1).

    Called on EVERY pass, whether or not the budget was spent: a kind
    registered in `NOTICE_KINDS` with a writer that only runs on the bad day
    renders [ OK ] the rest of the time, which is the exact "unchecked as
    fine" mistake finding 1 of the 08-28 fix pass was. Never raises: a
    database an older build migrated has no `notices` table, and the delivery
    that just happened must not be undone by the bookkeeping about it.
    """
    left = int(result.get("undelivered") or 0)
    try:
        if left:
            db.notice(
                conn, "alerts_delivery_slow", "warn", "delivery",
                body=(f"Sending this server's alerts took longer than the "
                      f"{int(ALERT_CYCLE_BUDGET_SECONDS)} seconds one pass is "
                      f"allowed, so {left} of them were left for the next pass. "
                      f"The usual cause is a mail server or a webhook that "
                      f"accepts the connection and then does not answer. "
                      f"Nothing has been lost: anything still wrong is offered "
                      f"again every cycle."),
                fix=("On Settings, Alerts: press [ SEND A TEST ] and time it. If "
                     "it hangs, correct the mail server or webhook address, or "
                     "switch the channel off until it is fixed."),
                now=now)
        else:
            db.clear_notice(conn, "alerts_delivery_slow", "delivery", now=now)
    except sqlite3.Error:
        log.exception("alerts: could not record the delivery budget")
