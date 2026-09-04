"""HTML routes and htmx partials. All view data comes from api.py's builders
so the JSON API and the pages can never disagree."""
from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
import sqlite3
from pathlib import Path

from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               RedirectResponse, Response)
from fastapi.templating import Jinja2Templates

from . import (VERSION, auth, dashboard_update, db, health, local_users,
               notices, oidc, package_store, provision, release_feed, site_store)
# UX-3: the /help route and the markdown renderer behind it. Aliased because
# `help` is a builtin, and imported here rather than the other way round --
# help.py defers its own `ui` import to call time, so this stays acyclic.
from . import help as help_page
from .api import (
    approve_username_error, build_admin_users_view, build_editors_view,
    build_packages_view, build_presence_view, build_project_view, build_projects_view,
    audit_plan_change, build_queue_view, build_report_tokens_view, build_transfers_view,
    delete_user_everywhere, forget_machine_everywhere, get_conn, normalize_device_id,
)
# The Users page's own writes, one implementation each (OPS-2 / DCORE-4,
# 2026-09-04): the button must never be a softer door than the JSON route.
from .api import approve_pending_ssh_key as api_approve_pending_ssh_key
from .api import _blank_key_refusal as api_blank_key_refusal
# The fleet-read redaction the JSON API applies, imported under a name that
# says where the rule lives: ONE definition, two callers (COMMERCIAL_READINESS.md
# §C L1, 2026-08-17). See api.py's "scoping fleet reads" block.
from .api import tick_capacity_warning
# The release-channel gate and the recall's fleet write (REL-1 / REL-3,
# resilience sweep 2026-08-28), imported under names that say they belong to
# the JSON routes: these htmx twins must apply the SAME refusals, not their
# own copies of them.
from .api import make_current_refusal as api_make_current_refusal
from .api import roll_fleet_back as api_roll_fleet_back_impl
from .api import _purge_user_credentials as api_purge_user_credentials
from .api import _scope_editors_view as api_scope_editors_view
from .api import _scope_projects_view as api_scope_projects_view
from .nas import NasBackend, NasError, is_valid_username, looks_like_ssh_pubkey
from .nas import factory as nas_factory
from .syncthing_client import SyncthingClient, SyncthingError

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
# The PWA's three routes read their own bodies out of static/ (see the
# "installable app" block at the end of this file).
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

router = APIRouter(default_response_class=HTMLResponse)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

log = logging.getLogger("ccsync.dashboard.ui")

# ONE message for every way a sign-in can be refused (2026-08-17,
# COMMERCIAL_READINESS.md item 15). "bad username or password" vs "too many
# attempts" vs "you are not an admin" is a username-and-role oracle for anyone
# who can reach the login page; the difference goes to the log, not the page.
_LOGIN_REFUSED = "sign-in refused - check your username and password, then try again"
# UX-22 (usability sweep 2026-09-03) asked for "no account with that name
# here" on an unknown username, and this build does NOT say it. Two reasons,
# both load-bearing: on every deployment that authenticates against the NAS
# (all of them today) the question cannot be answered without a second
# credential round-trip to the NAS from an unauthenticated route, which is a
# free enumeration oracle AND a way to make /login do work for anyone on the
# tailnet; and item 15 (2026-08-17) settled deliberately on ONE message for
# every refusal, because "wrong password" versus "no such user" is exactly
# the difference an attacker is looking for. The login page's answer to a
# person with no account is the muted line in login.html instead, which is
# true before they type anything.


def human_bytes(n) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def ago(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        stamp = db.parse_iso(ts)
    except ValueError:
        return ts
    if stamp.tzinfo is None:
        # A timestamp with no offset is read as UTC rather than refused: a
        # hand-minted auth_sessions row from the 2026-08-24 ship carried
        # `2026-08-24 03:16:18` and every render of the Sessions page 500'd
        # on the subtraction below for three days (seen 2026-08-27). A
        # filter used on pages that tell the fleet whether footage is
        # syncing must never be the reason a page does not render.
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    delta = dt.datetime.now(dt.timezone.utc) - stamp
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def bar(completion, width: int = 10) -> str:
    if completion is None:
        return "?" * width
    filled = round(max(0.0, min(float(completion), 100.0)) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def eta(seconds) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


templates.env.filters["human_bytes"] = human_bytes
templates.env.filters["ago"] = ago
templates.env.filters["bar"] = bar
templates.env.filters["eta"] = eta

# UX-8 (usability sweep 2026-09-03): ONE list, in one place. The Settings
# strip (partials/settings_nav.html) and the drawer's "which page lights
# [ SETTINGS ] up" test (partials/topbar.html) each carried their own copy,
# with a comment in the second asserting they matched; six pages were added
# to the strip and not to the copy, so an admin standing on ALERTS, JOBS,
# INVARIANTS, PROTECTION, RECOVERY or TIMELINE opened the phone drawer and
# found nothing marked at all. A thirteenth page cannot drift now: both
# templates read these globals.
#
# (key, label, href, admin_only). admin_only is per ENTRY, not per strip:
# /transfers is an editor-visible page that happens to hang here.
# SYS-6 (usability sweep 2026-09-03, wave 4): the strip grew from the owner's
# 2026-08-18 five to twelve flat entries in twelve days, six of them
# diagnostic pages from one sweep, and read as five separate products. It is
# THREE LABELLED RUNS now, and the groups are the list: SETTINGS_NAV is
# derived from them so nothing can be in a run and not in the strip, or the
# other way round.
#
# SETUP sits in "Run the fleet" and not in a run of its own: it is the only
# nav that serves the wizard, and a page dropped from the one navigation that
# reaches it is a page nobody finds again.
SETTINGS_NAV_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str, bool], ...]], ...] = (
    ("Run the fleet", (
        ("site",        "SITE",        "/admin/settings",    True),
        ("users",       "USERS",       "/admin/users",       True),
        # DUI-12 / the vocabulary table: the page is SYNC PLANS. "Assignment"
        # left the copy on 2026-09-04; the route, the view model and the
        # `selections` table keep their names.
        ("assignments", "SYNC PLANS",  "/admin/assignments", True),
        ("transfers",   "TRANSFERS",   "/transfers",         False),
        ("packages",    "PACKAGES",    "/admin/packages",    True),
        ("jobs",        "JOBS",        "/admin/jobs",        True),
        # DUI-12: three different things in this navigation were called a
        # timeline (a Resolve timeline, the mounted Timeline Cards, and the
        # audit log). The audit log is HISTORY. The route is unchanged.
        ("audit",       "HISTORY",     "/admin/audit",       True),
        ("setup",       "SETUP",       "/setup",             True),
    )),
    ("Is it healthy", (
        ("health",      "HEALTH",      "/admin/health",      True),
        ("invariants",  "INVARIANTS",  "/admin/invariants",  True),
        ("protection",  "PROTECTION",  "/admin/protection",  True),
        ("alerts",      "ALERTS",      "/admin/alerts",      True),
    )),
    ("When it breaks", (
        ("recovery",    "RECOVERY",    "/admin/recovery",    True),
        # UX-3: the customer explainer, served at /help. Not admin-only -- an
        # editor standing on Transfers is exactly who needs it.
        ("help",        "HELP",        "/help",              False),
    )),
)
SETTINGS_NAV: tuple[tuple[str, str, str, bool], ...] = tuple(
    entry for _group, entries in SETTINGS_NAV_GROUPS for entry in entries)
SETTINGS_PAGES: tuple[str, ...] = tuple(key for key, _, _, _ in SETTINGS_NAV)
# Where [ SETTINGS ] in the drawer and the topbar's gear land (SYS-6): the
# HEALTH page, not the site form. "Is everything all right" is the question an
# owner opens Settings with; renaming the studio is not.
SETTINGS_LANDING = "/admin/health"
templates.env.globals["SETTINGS_NAV"] = SETTINGS_NAV
templates.env.globals["SETTINGS_NAV_GROUPS"] = SETTINGS_NAV_GROUPS
templates.env.globals["SETTINGS_PAGES"] = SETTINGS_PAGES
templates.env.globals["SETTINGS_LANDING"] = SETTINGS_LANDING

# The three transports, in the words an editor reads (the vocabulary table,
# usability sweep 2026-09-03 section 4). api.LANE_LABELS stays "A" / "B" /
# "C" because the JSON API, the companion's reports and every log line use
# them; "lane" never reaches a visible string again. Keyed by the lane name
# the report carries, so a chip can name itself from `lane.lane`.
LANE_WORDS: dict[str, str] = {
    "lane_a_video_up": "upload",
    "lane_b_proxy_down": "proxy download",
    "lane_c_syncthing": "folder sync",
}


def lane_word(lane: str | None) -> str:
    """What to call one transport on a page. Unknown names answer with
    themselves: a companion reporting a lane this build has never heard of
    must still render a chip."""
    return LANE_WORDS.get(str(lane or ""), str(lane or ""))


templates.env.globals["lane_word"] = lane_word
templates.env.filters["lane_word"] = lane_word

# UX-3 / SYS-21: where a word on a page goes to be explained. Four surfaces
# link in here (the sync line and the status chips on SYNC STATUS, the tick
# modes on SYNC PLANS, and the topbar), so the anchor shape is written down
# once: a heading rename in the guide that moved the glossary would otherwise
# break four links silently.
GLOSSARY_HREF = f"/help#{help_page.GLOSSARY_ID}"


def term_href(term: str) -> str:
    """The deep link to one glossary row, e.g. term_href("sync plan")."""
    return f"/help#{help_page.TERM_PREFIX}{help_page.slugify(term)}"


templates.env.globals["GLOSSARY_HREF"] = GLOSSARY_HREF
templates.env.globals["term_href"] = term_href

# CR-88 (2026-08-27) route sweep, usability sweep 2026-09-03: the tray's
# right-click menu is ten items and Copy diagnostics is NOT one of them. It
# moved into the companion's Settings window, under HELP, and a dashboard
# sentence that tells an admin to tell an editor to "use Copy diagnostics on
# the tray" sends them looking for a menu item that is not there. ONE
# constant, because three surfaces say it (the diagnostics panel twice, the
# fleet grid's CRASHES chip) and alerts.py says it twice more.
COMPANION_DIAGNOSTICS_PATH = health.COMPANION_DIAGNOSTICS_PATH
templates.env.globals["COMPANION_DIAGNOSTICS_PATH"] = COMPANION_DIAGNOSTICS_PATH

# WHAT A CHIP MEANS, in one place (DUI-3, usability sweep 2026-09-03). Every
# chip on the fleet grid carried its whole explanation in `title=`, which a
# phone cannot show: eighteen labels can stack in one LANES cell and on a
# touch device the entire explanatory layer of the product's most important
# page was unreachable. static/htmx_errors.js now opens a sheet on a tap, and
# the sheet reads the same text the tooltip does -- so the text has to have
# ONE home, or the two drift and the phone gets the older sentence.
#
# Format strings, filled by chip_help(key, **values) from the template: the
# per-machine numbers are the template's, the prose is this dict's.
CHIP_HELP: dict[str, str] = {
    "relayed": (
        "{n} Syncthing peer(s) connected via a RELAY, not directly: folder sync "
        "on this computer is limited to relay speed (1-5 MB/s), not the link. "
        "Checked {at}."),
    "direct": "{n} Syncthing peer(s) connected directly. Checked {at}.",
    "orphans": (
        "{bytes} of orphaned rclone .partial files left on the NAS by an "
        "interrupted upload. Never deleted automatically; remove them by hand "
        "to reclaim the space."),
    "breaker": (
        "{reason}, stopped {at}. Upload and folder sync are still running; "
        "nothing was deleted."),
    "sync_engine_down": (
        "the Syncthing engine on this computer has been down since {since}"
        "{extra}"),
    "clock": (
        "this computer's clock is {abs} {direction} the server's. Proxy "
        "download uses a minimum file age, so a clock this far out can make it "
        "transfer nothing at all while reporting no error. Fix the clock on "
        "that computer (enable automatic time)."),
    "crashes": (
        "{n} background task(s) on this computer have crashed and written a "
        "report{newest}. The tray stays up and syncing looks normal, so ask "
        "the editor to open {path} in the companion and send it to you."),
    "report_refused": (
        "the last report from this computer was refused {at}: {reason}. "
        "Nothing below is current. The editor has to click Sign in... on this "
        "computer's tray."),
    "update_failed": (
        "this computer has tried to install {version} {n} time(s) and "
        "failed{when}{why}. Antivirus quarantine, a proxy mangling the "
        "download and a full disk all look like this."),
    "unfiltered": (
        "{n} Syncthing folder(s) on this computer have no ignore filter "
        "written{names}. Without it, folder sync carries camera originals both "
        "ways."),
    "conflicts": (
        "{n} Syncthing sync-conflict file(s) in this computer's tree. Two "
        "people saved one project file; nothing was lost, but somebody's edit "
        "is sitting in a renamed copy."),
    "out_of_tree": (
        "the project open on this computer references {n} clip(s) from "
        "outside the sync tree{bad_prefix}. They will never upload, so the "
        "timeline opens with red media on every other computer. Scanned "
        "{at}."),
    "stray_dirs": (
        "{n} project folder(s) on this computer's disk are not in the sync "
        "tree, holding {bytes}. Nothing in them is on the server or visible "
        "to anybody else."),
    "disk": (
        "this computer's sync drive has {free} free of {total}{system}. "
        "Measured {at}. Proxy download fills a drive file by file, and "
        ".ccsync-trash cannot prune while proxy download is stopped."),
    # `lane` is filled through ui.lane_word (fleet_grid.html), so this
    # reads "proxy download on this computer made no progress...".
    "stalled": (
        "{lane} on this computer made no progress for {seconds} "
        "second(s) {killed}, {at}. A local drive that stops answering reads "
        "exactly like this."),
    "skipped_exists": (
        "{n} file(s) exist on the NAS under the same name at a different "
        "size. Upload never overwrites a file already on the server, so this "
        "computer's newer versions will never go up."),
    "trash": (
        "{n} recoverable file(s) in this computer's .ccsync-trash. Pruned "
        "automatically after 14 days."),
    "gpu": "{name}{nvenc}{at}",
    "whisper": (
        "this computer has the whisper venv and the pipeline checkout the "
        "transcription jobs need"),
    "need_proxies": (
        "{n} clip(s) on this computer have no proxy yet, so nobody else on "
        "the fleet can see that footage{state}{left}."),
    "volunteering": (
        "somebody at {machine} clicked 'take fleet jobs now', so this "
        "computer is offered work while they use it - until {until} UTC, or "
        "until they click it off. Nothing else is bypassed: a stop, an update "
        "or a proxy download that stopped itself still refuse."),
    # RES-6 (2026-09-03): the cards role reported green while its loop was
    # dead or 401-ing, so `connected` alone is not the question any more. The
    # companion sends a state and a detail (builder C5, 2026-09-04) and the
    # chip's colour comes from the state, not from the connection.
    "cards_running": (
        "this computer is serving the Timeline Cards page from its own "
        "Resolve{timeline}{detail}{at}"),
    "cards_stopped": (
        "the Timeline Cards role on this computer has STOPPED: the page will "
        "not update until its companion is restarted.{detail}{at}"),
    "cards_refused": (
        "the Timeline Cards role on this computer refused to start."
        "{detail}{at}"),
    "cards_credential_refused": (
        "the Timeline Cards role on this computer is being refused by the "
        "dashboard (its credential is wrong or expired), so the page it "
        "serves is stale.{detail}{at}"),
    "cards_unreachable": (
        "the Timeline Cards role on this computer cannot reach the "
        "dashboard, so the page it serves is stale.{detail}{at}"),
    # CYT-3 (2026-09-03): the clips land on disk and never reach Resolve, and
    # until now that reached nobody at either end. `no-project-match` is a
    # per-machine misconfiguration an admin can fix and the editor cannot.
    "youtube_import": (
        "{n} YouTube clip(s) downloaded to this computer are waiting to go "
        "into Resolve{reason}. They are on the disk; nothing is lost. "
        "Reported {at}."),
    "youtube_import_gave_up": (
        "this computer gave up filing {n} downloaded YouTube clip(s) into "
        "Resolve: {reason}. They stay on the disk under Youtube/ and are "
        "retried when its companion restarts. Reported {at}."),
}


def chip_help(key: str, **values) -> str:
    """The sentence behind one chip, filled in. An unknown key and a missing
    value both answer with something rather than raising: this text is on the
    page that tells the fleet whether its footage is syncing, and a KeyError
    from a companion that reported one field fewer must never be why it does
    not render."""
    text = CHIP_HELP.get(key)
    if text is None:
        return ""
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


templates.env.globals["CHIP_HELP"] = CHIP_HELP
templates.env.globals["chip_help"] = chip_help


def safe_to_close(transfers_view: dict | None, editor: str | None) -> dict | None:
    """"Am I safe to close my laptop", in one line (DUI-19, sweep 2026-09-03).

    The editor's own page was good at what is moving and never composed the
    one sentence they came for: they had to read a percentage bar, a
    "12 files, 4.2 GB, ETA 26m" line and a [ GETTING READY ] chip and do the
    synthesis themselves. Nothing new is measured here - it is the transfers
    view the panel below already renders.

    UPLOADS are what decides it: a download interrupted by a closed lid
    resumes, an upload that has not happened yet leaves that footage on one
    disk. `None` for an admin's fleet-wide view, which has no "this computer".
    """
    if not transfers_view or not editor:
        return None
    live = [t for t in (transfers_view.get("transfers") or [])
            if (t.get("editor") or "") == editor]
    up_live = [t for t in live if t.get("direction") == "up"]
    down_live = [t for t in live if t.get("direction") != "up"]
    queues = [q for q in (transfers_view.get("queues") or [])
              if (q.get("editor") or "") == editor and not q.get("pending")]
    up_files = sum(int(q.get("n_files") or 0) for q in queues
                   if q.get("direction") == "up") + len(up_live)
    up_bytes = sum(int(q.get("bytes") or 0) for q in queues
                   if q.get("direction") == "up")
    for t in up_live:
        total, done = t.get("bytes_total"), t.get("bytes_done")
        if total is not None and done is not None:
            up_bytes += max(0, int(total) - int(done))
    down_files = sum(int(q.get("n_files") or 0) for q in queues
                     if q.get("direction") != "up") + len(down_live)
    speed = sum(int(t.get("speed_bps") or 0) for t in up_live)
    seconds = int(up_bytes / speed) if speed > 1 and up_bytes else None
    if not up_files:
        if down_files:
            sentence = (f"Safe to close: nothing from this computer is waiting to go to "
                        f"the server. {down_files} file(s) are still coming down and "
                        f"carry on where they left off next time.")
        else:
            sentence = "Safe to close: nothing is transferring."
        return {"safe": True, "sentence": sentence, "up_files": 0,
                "up_bytes": 0, "eta_seconds": None}
    about = f", about {eta(seconds)}" if seconds else ""
    sentence = (f"Not yet: {up_files} file(s) still uploading from this computer"
                f" ({human_bytes(up_bytes)}){about}. Leave it running.")
    return {"safe": False, "sentence": sentence, "up_files": up_files,
            "up_bytes": up_bytes, "eta_seconds": seconds}


def _render(request: Request, name: str, context: dict) -> HTMLResponse:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    context.setdefault("session_user", user)
    context.setdefault("session_is_admin", auth.is_admin(settings, user))
    # Every template gets it, because every partial can contain a form and a
    # partial re-rendered into the page must carry a live token (base.html puts
    # it on <body> as hx-headers, so htmx sends it on every request from the
    # page; partials/topbar.html republishes it for the mounted SPAs). "" for
    # an anonymous render -- there is no session to protect yet.
    context.setdefault("csrf_token", auth.csrf_token(request))
    # BRAND (2026-08-17, COMMERCIAL_READINESS.md item 10). The topbar used to
    # read "CREATORS CLUB" as a literal, in this template and in the three
    # SPAs' fallback headers. It is site data now, and the fallback chain is
    # org_short -> org_name -> product_name: an unbranded install shows the
    # PRODUCT's name, never the first customer's.
    #
    # From the RESOLVED manifest since 2026-08-21 (product-surface-2), not
    # `settings.site_*`: on an appliance the wizard's "Your studio" answers
    # are the only place org_name ever exists (no DASH_SITE_* in
    # compose.appliance.yaml), so reading the env snapshot here left an admin
    # looking at "CC SYNC" on a page whose Settings form showed the name they
    # had just saved. Cached on app.state and dropped by site_store.invalidate
    # on every write, so this stays one dict lookup per render.
    manifest = site_store.manifest_for_app(request.app, settings)
    # UX-5 (usability sweep 2026-09-03): every <title> reads this too now, so
    # the tab, the bookmark, the phone's app switcher and the login page all
    # say what the header says. The last "or" is what keeps a title from
    # rendering as an empty string on a site whose manifest could not be read:
    # the product's name is the floor, never the first customer's.
    context.setdefault("brand_org", (manifest.get("org_short")
                                     or manifest.get("org_name")
                                     or manifest.get("product_name")
                                     or settings.site_product_name
                                     or "CC Sync"))
    context.setdefault("brand_product", manifest.get("product_name")
                       or settings.site_product_name)
    # Which nav entry to mark (2026-08-18). The drawer in partials/topbar.html
    # and the Settings strip in partials/settings_nav.html read the same one
    # variable, so a page names where it is ONCE. Defaulted here because both
    # templates test it against a list, and an Undefined that reached a
    # `in SETTINGS_PAGES` would be a render error rather than "nothing marked".
    context.setdefault("nav_current", "")
    # Only offer the B-ROLL link when the mount FULLY took (broll.MOUNTED).
    # The import is guarded, so a missing or stale /broll-app leaves the
    # dashboard running with the feature absent; and a mount whose data root
    # could not be prepared is mounted "degraded", answering every request with
    # a 500. A nav link to either is worse than no link.
    context.setdefault("broll_mounted", getattr(request.app.state, "broll_mounted", False))
    # Identical rule for the music platform (music.MOUNTED only): a missing
    # music tree is absent, an unopenable DATA_ROOT is degraded, and neither
    # gets a nav link.
    context.setdefault("music_mounted", getattr(request.app.state, "music_mounted", False))
    # ...and for the YouTube downloader (ytdl.MOUNTED only). Same rule a third
    # time: absent tree or unusable YTDL_DATA_ROOT means no nav link.
    context.setdefault("ytdl_mounted", getattr(request.app.state, "ytdl_mounted", False))
    # ...and Timeline Cards (phase 3), on the same rule a fourth time. Its
    # "degraded" is spelt `absent` (cards.py's tri-state has no fourth state:
    # an engine that could not be built is not mounted at all), so this is
    # simply "did it fully take".
    context.setdefault("cards_mounted", getattr(request.app.state, "cards_mounted", False))
    # UX-10 (2026-08-28): how many problems the server has found, in the bar
    # that is on every page. FULL PAGES ONLY -- the partials re-render on 2 s
    # and 15 s timers, and a count on each of those would be one extra
    # connection per poll per open tab for a number nobody is reading in a
    # fragment. Best-effort: a topbar that cannot count must still render.
    # DUI-2 (2026-09-04): the topbar's freshness stamp on first paint. FULL
    # PAGES ONLY, and only for a session that can poll it -- the fragment
    # itself is behind the login gate. Its own connection for the same reason
    # the two counts below take one: _render has no request-scoped handle, and
    # a stamp is not worth threading one through every call site for.
    if not name.startswith("partials/") and context.get("session_user"):
        try:
            conn = db.connect(settings.db_path)
            try:
                context.update({k: v for k, v in _stamp_context(conn).items()
                                if k not in context})
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            log.exception("could not stamp this page render")
    if not name.startswith("partials/") and context.get("session_is_admin"):
        context.setdefault("notice_counts", _notice_counts_safe(settings))
        # SYS-8: the same idea for the alert scan, read from the LAST SCAN'S
        # stored counts rather than by scanning here. A scan walks the whole
        # fleet view and forty checks; doing that per page render would put
        # the cost of the diagnosis on every click, and the number a topbar
        # shows does not need to be fresher than the collector's cadence.
        context.setdefault("alert_counts", _alert_counts_safe(settings))
    return templates.TemplateResponse(request=request, name=name, context=context)


def _alert_counts_safe(settings) -> dict[str, int]:
    try:
        conn = db.connect(settings.db_path)
        try:
            stored = db.meta_get_json(conn, db.META_ALERTS_OPEN) or {}
        finally:
            conn.close()
        return {k: int(v) for k, v in stored.items() if k in ("error", "warn")}
    except Exception:  # noqa: BLE001
        log.exception("could not read the open-alert counts for the topbar")
        return {}


def _notice_counts_safe(settings) -> dict[str, int]:
    try:
        conn = db.connect(settings.db_path)
        try:
            return db.notice_counts(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("could not count open notices for the topbar")
        return {}


def _queue_editor(request: Request) -> str | None:
    """Whose queue to show: the session user, or ?as=<editor> for admins."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        return None
    target = request.query_params.get("as", "").strip().lower()
    if target and auth.is_admin(settings, user):
        return target
    return user


def _as_qs(request: Request, editor: str | None) -> str:
    """'&as=<editor>' when the viewer is ticking for somebody else, else ''.

    Every self-refreshing fragment that carries selection state has to thread
    this through: the sidebar polls /partials/sidebar every 30s, and a refresh
    that dropped ?as= re-rendered the checkboxes against the ADMIN'S OWN ticks
    while the admin believed they were still looking at the other editor's --
    so the next click silently ticked the project onto the admin's machine."""
    user = auth.get_session_user(request)
    if editor and user and editor.lower() != user.lower():
        return "&as=" + quote(editor, safe="")
    return ""


@router.get("/")
def page_fleet(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    queue_editor = _queue_editor(request)
    # ONE snapshot for both panels: the sidebar and the queue each used to
    # build the whole thing (collector status + lanes + the N+1 fetch_projects)
    # from their own `now`, so one page render was ~2x the queries and the two
    # panels could disagree by construction (DASH-6, 2026-08-14).
    projects_view = build_projects_view(conn)
    scope = auth.scope_for(request)
    context = {
        # _sidebar_context, not a bare view: the every-30s /partials/sidebar
        # refresh has always rendered the checkboxes, so building this page's
        # first paint without them made the sidebar sprout controls 30s in.
        **_sidebar_context(request, conn, None, projects_view=projects_view),
        # Scoped: an editor sees their own machines plus the summary counts,
        # an admin sees the fleet (COMMERCIAL_READINESS.md L1, 2026-08-17).
        "fleet": api_scope_editors_view(build_editors_view(conn), scope),
        "queue": build_queue_view(conn, queue_editor, projects_view=projects_view)
                 if queue_editor else None,
        # First paint for the windowed live-transfers panel (2026-08-18). The
        # panel polls /partials/transfers every 2s like the /transfers page
        # does, so this build costs one extra pass on page load and nothing
        # after it -- rendered server-side rather than left to hx-trigger=load
        # so the window is never a blank 35vh hole while the first poll flies.
        "transfers": build_transfers_view(conn, editor=scope.editor),
        "scope_admin": scope.admin,
        "nav_current": "fleet",
    }
    # DUI-19: the editor's own answer to "am I safe to close my laptop",
    # from the view above rather than a second pass.
    context["safe_to_close"] = safe_to_close(context["transfers"], scope.editor)
    if queue_editor:
        context.update(_roots_context(
            conn, auth.is_admin(settings, auth.get_session_user(request))
        ))
    return _render(request, "fleet.html", context)


def _safe_next(raw: str) -> str:
    """Only same-site absolute paths survive; anything else (external URLs,
    protocol-relative //host tricks, and the backslash variant '/\\host')
    falls back to '/'."""
    raw = str(raw or "").strip()
    if raw.startswith("/") and not (len(raw) > 1 and raw[1] in "/\\"):
        return raw
    return "/"


def _login_context(request: Request, next_path: str, error: str | None,
                   local: bool) -> dict:
    settings = request.app.state.settings
    sso = str(settings.auth_method or "").strip().lower() == "oidc"
    return {
        "error": error,
        "next_path": next_path,
        # With OIDC configured the password form is BREAK-GLASS only: hidden
        # behind ?local=1 and, when it is shown, restricted to DASH_ADMIN_USERS
        # (see page_login_submit). An IdP outage must not lock the operator out
        # of their own dashboard; it must not quietly reopen password login for
        # the whole fleet either.
        "sso_enabled": sso,
        "show_password_form": (not sso) or local,
        "sso_url": f"{oidc.LOGIN_PATH}?next={quote(next_path, safe='')}",
        "local_url": f"/login?local=1&next={quote(next_path, safe='')}",
    }


@router.get("/login")
def page_login(request: Request):
    next_path = _safe_next(request.query_params.get("next", ""))
    if auth.get_session_user(request):
        return RedirectResponse(next_path, status_code=303)
    settings = request.app.state.settings
    if auth.refuse_plaintext_login(settings, request):
        # DASH_COOKIE_SECURE=1 says the cookie only ever crosses TLS; serving
        # the form on a plain-http connection under that promise sends the
        # password in clear AND has the browser drop the cookie afterwards, so
        # the editor loops on this page with no error anywhere (2026-08-17,
        # COMMERCIAL_READINESS.md item 6).
        raise HTTPException(
            status_code=400,
            detail="this dashboard is configured for https only (DASH_COOKIE_SECURE=1) "
                   "but you reached it over http -- use the https URL",
        )
    local = request.query_params.get("local", "") == "1"
    return _render(request, "login.html", _login_context(request, next_path, None, local))


MAX_LOGIN_BODY_BYTES = 8 * 1024   # generous for a username/password/next form
MAX_FORM_FIELDS = 16


@router.post("/login")
async def page_login_submit(request: Request):
    # /login is unauthenticated (app.py's _OPEN_EXACT), so an unbounded body
    # read here is a single-worker OOM open to anyone on the tailnet -- check
    # Content-Length BEFORE reading, and re-check the actual body length as a
    # fallback for chunked/absent-header requests (see the unbounded /login
    # body finding).
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_too_big = int(content_length) > MAX_LOGIN_BODY_BYTES
        except ValueError:
            declared_too_big = True
        if declared_too_big:
            raise HTTPException(status_code=413, detail="request body too large")
    body = await request.body()
    if len(body) > MAX_LOGIN_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        parsed = parse_qs(body.decode(), max_num_fields=MAX_FORM_FIELDS)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed form body")
    form = {k: v[0] for k, v in parsed.items()}
    settings = request.app.state.settings
    username = form.get("username", "").strip().lower()
    password = form.get("password", "")
    next_path = _safe_next(form.get("next", ""))
    local = request.query_params.get("local", "") == "1" or form.get("local", "") == "1"
    sso = str(settings.auth_method or "").strip().lower() == "oidc"
    error = None
    if not settings.session_secret:
        error = "login not configured on the server (DASH_SESSION_SECRET unset)"
    elif auth.refuse_plaintext_login(settings, request):
        error = ("this dashboard is configured for https only (DASH_COOKIE_SECURE=1) "
                 "-- use the https URL")
    elif (throttled_for := auth.login_throttled(request, username)):
        # DCORE-8 (2026-09-04): the wait is NAMED now. The username-oracle
        # worry this branch was written with does not apply to it: every
        # failed sign-in records a failure whether or not the account exists
        # (auth.record_login_failure is unconditional), so a made-up name is
        # throttled, and told the same wait, as a real one. What the generic
        # message still protects is the OUTCOME of a sign-in that was
        # actually tried -- this page never says which half was wrong.
        error = auth.throttle_message(throttled_for)
    elif sso and not auth.is_admin(settings, username):
        # Break-glass is for the operator, not a password back door for the
        # fleet. Same generic message, so it does not disclose who is an admin.
        log.warning("local password login refused for non-admin %r while "
                    "DASH_AUTH_METHOD=oidc", username)
        auth.record_login_failure(request, username)
        error = _LOGIN_REFUSED
    else:
        verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)
        # verifier is a blocking SMB session setup (up to a 10s timeout) --
        # push it off the event loop so a slow/unreachable SMB server can't
        # freeze every other request, including companions' /api/v1/report
        # (see SEC-13 / the ui.py blocking-handlers finding).
        try:
            verified = await run_in_threadpool(verifier, settings, username, password)
        except auth.CredentialProbeBusy:
            # Saturated probe pool (see auth.MAX_CONCURRENT_SMB_PROBES): this
            # is NOT a failed password, so it must not count toward the
            # throttle either.
            error = "the server is busy checking sign-ins -- try again in a moment"
        else:
            if verified:
                auth.clear_login_failures(request, username)
                landing = next_path
                # First-run steering (ZERO_TOUCH_PLAN.md WP D, 2026-08-17):
                # an admin who did not ask for a specific page (no ?next=,
                # so next_path fell back to "/") lands on /setup instead of
                # the fleet grid while a required step is still outstanding
                # -- "the login gate's post-login landing is /setup instead
                # of the grid." Never for a non-admin (do not trap editors
                # in a page they cannot act on), and best-effort: a DB that
                # cannot be read must never block a login.
                if landing == "/" and auth.is_admin(settings, username):
                    try:
                        conn = db.connect(settings.db_path)
                        try:
                            from . import setup_engine

                            if setup_engine.outstanding_required(conn):
                                landing = "/setup"
                        finally:
                            conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                response = RedirectResponse(landing, status_code=303)
                # Mints the cookie AND the revocable server-side session row;
                # see auth.start_session (cookie flags: Secure per
                # auth.cookie_secure, HttpOnly, SameSite=Lax).
                auth.start_session(request, response, username)
                log.info("login for %r from %s", username, auth.client_ip(request))
                return response
            auth.record_login_failure(request, username)
            error = _LOGIN_REFUSED
    return _render(request, "login.html", _login_context(request, next_path, error, local))


@router.post("/logout")
def page_logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    # Revokes the server-side row too: deleting the browser's copy alone left
    # a stolen cookie valid for the rest of its lifetime (item 6 / H1).
    auth.end_session(request, response)
    return response


@router.post("/logout-everywhere")
def page_logout_everywhere(request: Request):
    """"Sign me out on every device." The one thing an editor who thinks their
    laptop was taken can do without waiting for an admin."""
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="not logged in")
    store = auth.session_store(request)
    revoked = store.revoke_user(user, by=f"self:{user}") if store else 0
    log.warning("%r revoked %d session(s) from every device", user, revoked)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


@router.get("/partials/topbar")
def partial_topbar(request: Request, current: str = "",
                   conn: sqlite3.Connection = Depends(get_conn)):
    """The shared header, fetched by the mounted SPAs (/broll, /music) so their
    pages carry the dashboard's real topbar -- session, admin links, nav --
    instead of a hand-copied imitation that drifts. `current` names the nav
    entry for the page doing the fetching; anything unrecognized simply
    highlights nothing.

    The freshness stamp comes with it since DUI-2 (2026-09-04): it used to be
    left out here because no `view` was passed, so an SPA's header said
    nothing about whether the server was still answering. It is its own read
    now (_stamp_context), not the fleet view, so this stays one cheap query."""
    return _render(request, "partials/topbar.html",
                   {"nav_current": current.strip().lower(),
                    **_stamp_context(conn)})


# ----------------------------------------------------------- freshness stamp
#
# DUI-2 (usability + resilience sweep, 2026-09-04). The page's ONLY freshness
# indicator was `updated {{ view.generated_at | ago }}` inside
# partials/topbar.html, which is a plain {% include %} rendered once per full
# page load and never again. So a dashboard whose partials had been 500ing for
# an hour -- a container restart, a NAS reboot, a wifi drop -- kept painting a
# green fleet with "updated 4s ago" beside it, indefinitely. Two halves fix
# that and they are deliberately independent: this fragment can only say "4s"
# while the server is answering, and static/htmx_errors.js says so out loud
# when it stops.
#
# The stamp is the SERVER's own clock at the moment it answered, not the fleet
# view's generated_at: what the reader needs from it is "is this page still
# talking to the dashboard", and a view builder's timestamp cannot answer that
# on a page that has no view.

def _stamp_context(conn) -> dict:
    """When the server last answered this page, and whether Syncthing is up.

    The Syncthing banner rides in the same fragment because it was frozen into
    the same include: "data may be stale" that itself goes stale is worse than
    no banner at all."""
    try:
        collector = db.fetch_collector_status(conn)
        reachable = bool(collector["syncthing_reachable"])
    except Exception:  # noqa: BLE001
        # A topbar that cannot read the collector must still render, and must
        # not accuse Syncthing of being down on the strength of a failed read.
        log.exception("could not read collector status for the freshness stamp")
        reachable = True
    return {"stamp_at": db.utcnow_iso(), "stamp_syncthing_reachable": reachable}


@router.get("/partials/stamp")
def partial_stamp(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The polled half of DUI-2. Every open tab asks for this on its own
    cadence, so it is kept to one collector read and no view build."""
    return _render(request, "partials/stamp.html", _stamp_context(conn))


@router.get("/partials/queue")
def partial_queue(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The queue panel AND the destination-root panel below it.

    One fragment for two panels since 2026-08-18, when [ FIX DESTINATION ROOT ]
    moved out of the queue box: both read one build_queue_view, so a route of
    its own for the root line would rebuild the whole queue every 10s to
    re-render one sentence.
    """
    editor = _queue_editor(request)
    if editor is None:
        raise HTTPException(status_code=401, detail="not logged in")
    # DUI-19: the same sentence the transfers panel carries, on the panel an
    # editor actually reads. It is built from the transfers view because that
    # is where "what is still going up" lives; the 10s poll pays for one
    # editor-scoped build, not a fleet one.
    transfers = build_transfers_view(conn, editor=editor)
    return _render(request, "partials/queue_section.html", {
        "queue": build_queue_view(conn, editor),
        "safe_to_close": safe_to_close(transfers, editor),
    })


def _roots_context(conn: sqlite3.Connection, is_admin: bool) -> dict:
    from .api import _project_roots_view

    projects = [
        {"slug": r["slug"], "label": r["label"]}
        for r in conn.execute("SELECT slug, label FROM projects WHERE active=1 ORDER BY label")
    ]
    return {"roots": {
        "mappings": _project_roots_view(conn),
        "unmapped": db.fetch_unmapped_resolve_projects(conn),
        "projects": projects,
        "is_admin": is_admin,
    }}


@router.get("/partials/project-roots")
def partial_project_roots(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    is_admin = auth.is_admin(settings, auth.get_session_user(request))
    return _render(request, "partials/project_roots.html", _roots_context(conn, is_admin))


@router.post("/partials/project-roots")
async def partial_set_project_root(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None or not auth.is_admin(settings, user):
        raise HTTPException(status_code=403 if user else 401,
                            detail="admins only: destination roots are fixed once set")
    form = await _form(request)          # field-capped like every other partial (DASH-3)
    name = form.get("resolve_project", "").strip()
    slug = form.get("root", "").strip() or None
    # A rel path picked in the folder browser (any folder under Projects/,
    # not only registered projects). The companion only ever consumes the
    # mapping as a rel path (_project_roots_view falls back to the raw
    # stored value), so an unregistered folder works end to end.
    root_rel = form.get("root_rel", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="resolve_project required")
    if root_rel:
        from .api import ProjectSetupError, _safe_rel

        try:
            target, norm_rel = _safe_rel(settings, root_rel)
        except ProjectSetupError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if not norm_rel or not target.is_dir():
            raise HTTPException(status_code=404, detail=f"no such folder under Projects/: {root_rel!r}")
        # Prefer the slug when the picked folder IS a registered project, so
        # the dropdown keeps showing it as selected.
        marker_slug = provision.read_marker(target)
        db.admin_set_project_root(conn, name, marker_slug or norm_rel,
                                  admin=user, now=db.utcnow_iso())
    elif slug is None:
        db.delete_project_root(conn, name)
    else:
        exists = conn.execute(
            "SELECT 1 FROM projects WHERE slug=? AND active=1", (slug,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
        db.admin_set_project_root(conn, name, slug, admin=user, now=db.utcnow_iso())
    conn.commit()
    return _render(request, "partials/project_roots.html", _roots_context(conn, True))


@router.get("/partials/project-roots/browse")
def partial_project_roots_browse(
    request: Request, resolve_project: str = "", rel: str = ""
):
    """The FILES INTO folder browser: any folder under Projects/ can be
    picked as a Resolve project's destination root, not only the dropdown's
    registered projects. Admin-gated like the setter it feeds."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None or not auth.is_admin(settings, user):
        raise HTTPException(status_code=403 if user else 401,
                            detail="admins only: destination roots are fixed once set")
    return _render(request, "partials/project_roots_browse.html",
                   _browse_context(request, resolve_project, rel))


# -------------------------------------------------- project setup (new-project)

def _browse_context(request: Request, resolve_project: str, rel: str) -> dict:
    """The folder-browser box: children of `rel` under the Projects tree,
    each flagged is_project (marker present) and name_match (same name as the
    Resolve project -- almost always the folder the editor means). Tolerant:
    an invalid rel or unmounted tree degrades to an error entry, never a
    crash.

    can_link_current says whether the folder you are STANDING IN may itself be
    picked: without that button, drilling into an already-existing project
    folder left "create a new subfolder here" as the only action, which is how
    <project>/<project> double-nesting happened."""
    from .api import ProjectSetupError, _marked_ancestor, _safe_rel

    settings = request.app.state.settings
    error = None
    entries: list[dict] = []
    crumbs: list[dict] = []
    inside_project = False
    current_is_project = False
    norm_rel = ""
    wanted = resolve_project.strip().casefold()
    try:
        target, norm_rel = _safe_rel(settings, rel)
        projects_dir = Path(settings.projects_dir)
        if norm_rel:
            acc = []
            for part in norm_rel.split("/"):
                acc.append(part)
                crumbs.append({"name": part, "rel": "/".join(acc)})
            marked = _marked_ancestor(projects_dir, norm_rel)
            inside_project = marked is not None
            current_is_project = marked == norm_rel
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            child_rel = f"{norm_rel}/{child.name}" if norm_rel else child.name
            slug = provision.read_marker(child)
            # Per-CHILD try, not the outer one: this probe only decides a
            # link's label, and it used to be able to end the whole listing.
            # One unreadable sibling (0700 from a hand-copy under another uid,
            # or an ESTALE/EIO from the NFS-backed /projects mount) raised out
            # to the OSError handler below, so every alphabetically later
            # folder silently vanished from the picker AND can_link_current
            # went false -- the editor lost both the folder they came for and
            # [ USE THIS FOLDER ] (DASH-5, 2026-08-14).
            has_children = False
            if slug is None:
                try:
                    has_children = any(
                        g.is_dir() and not g.name.startswith(".") for g in child.iterdir()
                    )
                except OSError:
                    pass   # unreadable: it just doesn't get the "drill in" label
            entries.append({
                "name": child.name,
                "rel": child_rel,
                "is_project": slug is not None,
                "slug": slug,
                "has_children": has_children,
                "name_match": bool(wanted) and child.name.casefold() == wanted,
            })
    except ProjectSetupError as exc:
        error = str(exc)
    except OSError as exc:
        error = f"could not list the folder: {exc}"

    return {"browse": {
        "resolve_project": resolve_project.strip(),
        "rel": norm_rel,
        "crumbs": crumbs,
        "inside_project": inside_project,
        "current_is_project": current_is_project,
        # the current folder is pickable unless it sits inside a DIFFERENT
        # project (projects cannot nest) -- adopt_folder re-checks all of this
        "can_link_current": bool(norm_rel) and error is None
                            and (not inside_project or current_is_project),
        "entries": entries,
        "error": error,
    }}


def _setup_context(
    request: Request, conn: sqlite3.Connection, resolve_project: str,
    error: str | None = None, created: dict | None = None, browse_rel: str = "",
    suggest_rel: str = "",
) -> dict:
    from .api import _project_roots_view

    settings = request.app.state.settings
    user = auth.get_session_user(request)
    name = resolve_project.strip()
    mapping = None
    for row in _project_roots_view(conn):
        if row["resolve_project"].strip().lower() == name.lower():
            mapping = row
            break
    projects_dir = str(getattr(settings, "projects_dir", "") or "")
    projects_dir_ok = bool(projects_dir) and Path(projects_dir).is_dir()
    context = {"setup": {
        "resolve_project": name,
        "mapping": mapping,
        "is_admin": auth.is_admin(settings, user),
        "projects_dir_ok": projects_dir_ok,
        # The template the create actually lays down, from the resolved
        # manifest (dash-admin-3, 2026-08-21): this preview used to render
        # provision.TEMPLATE_FOLDERS, the import-time env/default list, so a
        # site whose wizard answer said "Footage, Audio, Graphics" was shown
        # -- and given -- the documentary defaults instead.
        "template_folders": site_store.template_folders(conn, settings),
        "error": error,
        # rel of an existing folder the failed action should have used --
        # rendered next to the banner as a one-click [ USE THIS FOLDER ]
        "suggest_rel": suggest_rel,
        "created": created,
    }}
    if projects_dir_ok:
        context.update(_browse_context(request, name, browse_rel))
    else:
        context["browse"] = None
    return context


@router.get("/project-setup")
def page_project_setup(
    request: Request, resolve_project: str = "", conn: sqlite3.Connection = Depends(get_conn)
):
    if not resolve_project.strip():
        return RedirectResponse("/", status_code=303)
    return _render(request, "project_setup.html", {
        **_sidebar_context(request, conn, None),
        **_setup_context(request, conn, resolve_project),
    })


@router.get("/partials/project-setup/browse")
def partial_project_setup_browse(
    request: Request, rel: str = "", resolve_project: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
):
    if auth.get_session_user(request) is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return _render(request, "partials/project_setup_panel.html",
                   _setup_context(request, conn, resolve_project, browse_rel=rel))


def _link_folder_sync(settings, conn, rel: str, name: str, user: str, existing) -> dict:
    """Runs on a threadpool worker -- see partial_project_setup_link. Does a
    depth-8 os.walk of the whole Projects tree plus marker writes."""
    from .api import adopt_folder

    created = adopt_folder(settings, conn, rel, name if existing is None else "", user)
    if existing is not None:
        # admin re-pointing an existing mapping
        db.admin_set_project_root(conn, name, created["slug"], admin=user, now=db.utcnow_iso())
        created["mapped"] = True
    conn.commit()
    return created


@router.post("/partials/project-setup/link")
async def partial_project_setup_link(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Link the browsed folder to the Resolve project: adopt_folder claims
    the directory (marker + projects row) and does the tiered sticky map.
    Already-mapped Resolve projects: sticky insert returns False -> banner
    (adopt_folder itself only touches project_roots via sticky, so a
    non-admin can never overwrite an existing mapping)."""
    from .api import ProjectSetupError

    settings = request.app.state.settings
    user = auth.get_session_user(request)
    form = await _form(request)
    name = form.get("resolve_project", "").strip()
    rel = form.get("rel", "").strip()

    error = None
    created = None
    if user is None:
        error = "not signed in"
    elif not rel:
        error = "pick a folder to link"
    else:
        existing = conn.execute(
            "SELECT 1 FROM project_roots WHERE resolve_project=?", (name,)
        ).fetchone() if name else None
        if existing is not None and not auth.is_admin(settings, user):
            error = "this Resolve project is already mapped -- ask an admin to change it"
        else:
            try:
                # Full-tree NAS I/O off the event loop: this walk takes tens of
                # seconds on a loaded NAS, and blocking here freezes every
                # companion report and every htmx poll (see the blocking
                # project-setup handlers finding).
                created = await run_in_threadpool(
                    _link_folder_sync, settings, conn, rel, name, user, existing
                )
            except ProjectSetupError as exc:
                error = str(exc)

    return await run_in_threadpool(
        _render_setup_panel, request, conn, name, error, created,
        rel.rsplit("/", 1)[0] if "/" in rel else "",
    )


def _create_project_sync(settings, conn, parent_rel: str, name: str,
                          resolve_project: str, user: str) -> dict:
    """Runs on a threadpool worker -- see partial_project_setup_create."""
    from .api import create_tree_project

    created = create_tree_project(settings, conn, parent_rel, name, resolve_project, user)
    # DCORE-5 (2026-09-04): the same audit row the JSON route writes. THIS is
    # the path an editor's own NEW PROJECT button takes, and a project it
    # creates is permanent until an admin archives it -- so "who made this"
    # must not depend on which of the two doors was used.
    db.audit(conn, user, "project.create", str(created.get("slug") or ""),
             {"label": created.get("rel") or ""})
    conn.commit()
    return created


@router.post("/partials/project-setup/create")
async def partial_project_setup_create(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    from .api import FolderExistsError, ProjectSetupError

    user = auth.get_session_user(request)
    form = await _form(request)
    name = form.get("resolve_project", "").strip()
    parent_rel = form.get("parent_rel", "").strip()

    error = None
    created = None
    suggest_rel = ""
    if user is None:
        error = "not signed in"
    else:
        try:
            created = await run_in_threadpool(
                _create_project_sync, request.app.state.settings, conn,
                parent_rel, form.get("name", ""), name, user,
            )
        except FolderExistsError as exc:
            # the typed name is already a folder here -- offer it instead of
            # making the admin invent a second, nested name
            error, suggest_rel = str(exc), exc.rel
        except ProjectSetupError as exc:
            error = str(exc)

    return await run_in_threadpool(
        _render_setup_panel, request, conn, name, error, created, parent_rel, suggest_rel
    )


def _render_setup_panel(request: Request, conn, name: str, error, created, browse_rel: str,
                        suggest_rel: str = ""):
    """_setup_context does per-row iterdir() over the NAS mount, so rendering
    the panel is itself blocking work -- always call this in a threadpool."""
    return _render(request, "partials/project_setup_panel.html",
                   _setup_context(request, conn, name, error=error, created=created,
                                  browse_rel=browse_rel, suggest_rel=suggest_rel))


@router.post("/partials/selection/{editor}/{slug}/toggle")
def partial_toggle(
    editor: str, slug: str, request: Request, machine: str | None = None,
    mode: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn)
):
    """The htmx checkbox. No `?machine=` means the PERSON, exactly like
    `PUT /api/v1/selection/{editor}/{slug}` with none.

    `machine` exists so this fragment endpoint cannot become the way around a
    refusal its JSON sibling makes (dash-admin-8 / CR-49, 2026-08-21): the
    same 404 for a computer this account has never reported and the same 409
    for a WIRED one, which works directly off the NAS tree and would sit under
    a permanent [ GETTING READY ] chip against a tick that can never clear.

    `mode` (docs/UPLOAD_ONLY_TICK.md) turns the toggle into a SET: with
    `?mode=upload_only` or `?mode=full` the project ends up ticked in that
    mode whether or not it was ticked before, and nothing is ever unticked
    by it. Without it the control is the plain toggle it always was, and
    unticking an upload-only project is the same untick as any other.
    """
    from .api import _sync_mode_arg

    settings = request.app.state.settings
    editor = editor.strip().lower()
    user = auth.get_session_user(request)
    if not auth.can_manage(settings, user, editor):
        raise HTTPException(status_code=403 if user else 401, detail="not allowed")
    target = (machine or "").strip() or None
    if target is not None and target not in db.machines_of(conn, editor):
        raise HTTPException(status_code=404,
                            detail=f"{editor} has no computer named {target!r}")
    wanted = _sync_mode_arg(mode) if (mode or "").strip() else None
    ticked = {s["slug"] for s in db.fetch_selections(conn, editor, machine=target)}
    # SYS-11 / DASH-8 (resilience sweep 2026-08-28). Snapshot, act, record:
    # the same three lines as the JSON route, because a ledger the checkbox
    # can walk past reads as "nobody did that".
    before = db.selection_placements(conn, editor, slug, machine=target)
    action = db.AUDIT_UNTICK if (slug in ticked and wanted is None) else db.AUDIT_TICK
    if slug in ticked and wanted is None:
        db.remove_selection(conn, editor, slug, machine=target)
    else:
        project = conn.execute(
            "SELECT slug FROM projects WHERE slug=? AND active=1", (slug,)
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
        if editor in db.base_only_editors(conn):
            # Same refusal as PUT /api/v1/selection (CR-28) -- the checkbox is
            # rendered disabled for a base rig, and this is the path a stale
            # page or a second tab would still take.
            raise HTTPException(
                status_code=409,
                detail="every computer on this account is wired to the server: they "
                       "work directly off the NAS and sync nothing, so "
                       "projects cannot be ticked for them",
            )
        if target is not None and (editor, target) in db.base_machines(conn):
            # CR-28 per MACHINE (dash-admin-8, 2026-08-21). The refusal above
            # is per PERSON and so cannot see a mixed account: one wired
            # desktop and one remote laptop under one name is a shape a site
            # can have (commit f27c181). The person-level path below needs no
            # such check -- db.add_selection_for_person skips a person's wired
            # machines itself.
            raise HTTPException(
                status_code=409,
                detail=f"{target} is wired to the server: it works directly off the "
                       "NAS and syncs nothing, so projects cannot be ticked for it",
            )
        sync_mode = wanted or db.SYNC_MODE_FULL
        if target is None:
            # The sidebar checkbox is the PERSON: every computer they use. Its
            # title says so, and the assignments grid is where one machine at a
            # time lives (MULTI_MACHINE_PLAN.md WP5).
            db.add_selection_for_person(conn, editor, slug, created_by=user,
                                        now=db.utcnow_iso(), sync_mode=sync_mode)
        else:
            db.add_selection(conn, editor, slug, created_by=user,
                             now=db.utcnow_iso(), machine=target,
                             sync_mode=sync_mode)
    audit_plan_change(conn, user, action, editor, slug, target, before,
                      db.selection_placements(conn, editor, slug, machine=target))
    conn.commit()
    # Reconcile Syncthing sharing promptly -- ticking used to wait out
    # interval_enforce (up to 60s) before anything started (2026-07-26).
    from .api import _nudge_collector

    _nudge_collector(request)
    # Return the partial the control lives in.
    view_kind = request.query_params.get("view")
    # Re-render for `editor` (the POST path), not for whoever _queue_editor
    # would infer: an admin ticking for someone else must get that editor's
    # checkboxes back, not their own.
    if view_kind == "sidebar" or "sidebar" in (request.headers.get("hx-target") or ""):
        current = request.query_params.get("slug_page")
        return _render(request, "partials/sidebar.html",
                       _sidebar_context(request, conn, current, editor=editor))
    if view_kind == "project":
        page_slug = request.query_params.get("slug_page", slug)
        view = build_project_view(conn, page_slug)
        if view is None:
            raise HTTPException(status_code=404)
        return _render(request, "partials/project_detail.html",
                       {"project": view,
                        "selected_by": db.fetch_all_selections(conn),
                        "selected_modes": db.fetch_all_selection_modes(conn),
                        "moves": db.file_moves_for_project(conn, page_slug),
                        "move_projects": [dict(r) for r in conn.execute(
                            "SELECT slug, label FROM projects WHERE active=1 ORDER BY label")],
                        "tick_editor": editor,
                        # DASH-8: the person-level untick confirm (see
                        # _sidebar_context; this render does not build one).
                        "toggle_editor_machines": db.machines_of(conn, editor),
                        "as_qs": _as_qs(request, editor)})
    return _render(request, "partials/my_queue.html", {
        "queue": build_queue_view(conn, editor, machine=target),
    })


@router.get("/project/{slug}")
def page_project(slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    scope = auth.scope_for(request)
    tick_editor = _queue_editor(request)
    return _render(request, "project.html", {
        **_sidebar_context(request, conn, slug),
        "project": view,
        "presence": build_presence_view(conn, slug, editor=scope.editor),
        "selected_by": db.fetch_all_selections(conn),
        "selected_modes": db.fetch_all_selection_modes(conn),
        "moves": db.file_moves_for_project(conn, slug),
        "move_projects": [dict(r) for r in conn.execute(
            "SELECT slug, label FROM projects WHERE active=1 ORDER BY label")],
        # DCORE-16 (usability sweep 2026-09-04): the config/enforce cycles
        # that did not do everything they described. This is the page where
        # somebody asks why a computer is not getting THIS project, and "a
        # sharing change is held" was recorded, alerted on, and rendered
        # nowhere near the question. Empty is the normal state and renders as
        # nothing.
        "enforce_notes": db.enforce_notes(conn),
        "scope_admin": scope.admin,
        "tick_editor": tick_editor,
        # A project page is a page OF the fleet grid, so the drawer keeps
        # [ SYNC STATUS ] lit rather than marking nothing at all.
        "nav_current": "fleet",
    })


def _sidebar_context(request: Request, conn, current: str | None,
                     editor: str | None = None,
                     projects_view: dict | None = None) -> dict:
    """Sidebar data incl. the checkbox state for the viewer's own selection
    (or the ?as=<editor> focus for admins).

    `editor` pins the target explicitly; toggle re-renders pass the editor
    from the POST path so the fragment that comes back can never disagree
    with the row that was just ticked.

    `projects_view` is the same snapshot-sharing hatch build_queue_view has --
    the fleet page renders both off one build (DASH-6, 2026-08-14)."""
    toggle_editor = editor or _queue_editor(request)   # session user, or ?as for admins
    selected = set()
    upload_only: set[str] = set()
    if toggle_editor:
        selected = {s["slug"] for s in db.fetch_selections(conn, toggle_editor)}
        # Marked, not a separate checkbox: the sidebar box is the person's
        # "I want this project"; the mode lives on the project page and the
        # assignments grid (docs/UPLOAD_ONLY_TICK.md).
        upload_only = {
            slug for slug, by_editor in db.fetch_all_selection_modes(conn).items()
            if by_editor.get(toggle_editor) == db.SYNC_MODE_UPLOAD_ONLY
        }
    return {
        **_switcher_context(request, conn, current, toggle_editor),
        "view": projects_view if projects_view is not None else build_projects_view(conn),
        "current_slug": current or None,
        "selected_slugs": selected,
        "upload_only_slugs": upload_only,
        "toggle_editor": toggle_editor,
        # CR-28: the base rig's checkboxes are disabled rather than absent --
        # an existing tick still has to be visible (and removable) on the
        # account that has one.
        "toggle_editor_base": bool(
            toggle_editor and toggle_editor in db.base_only_editors(conn)
        ),
        # DASH-8 (2026-08-28): the sidebar checkbox and the project page's
        # [ UNTICK FOR ... ] are PERSON-level, so an untick takes the project
        # off every computer that person owns. The confirm names them, which
        # is the whole difference between an informed click and CR-49's
        # "unticked the wrong row and the fleet unshared it".
        "toggle_editor_machines": db.machines_of(conn, toggle_editor) if toggle_editor else [],
        # UX-1 (resilience sweep 2026-08-28): what ticking THIS page's project
        # onto that person's computers would cost, in one sentence, so the
        # confirm can say it before the write. Only for the current project:
        # the sidebar's other rows are a tree of a hundred checkboxes and the
        # figure that matters is the one the owner is looking at.
        "tick_warning": (
            tick_capacity_warning(conn, toggle_editor, current)
            if toggle_editor and current else None
        ),
    }


def _switcher_context(request: Request, conn, current: str | None,
                      target: str | None) -> dict:
    """The admin-only 'ticking for <editor>' control, plus the ?as= fragment
    every self-refreshing partial on the page has to carry.

    Lives apart from _sidebar_context because the fleet page has no sidebar
    checkboxes -- there the switcher retargets the SYNC QUEUE panel instead,
    which is that page's ticking UI."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    others: list[str] = []
    if auth.is_admin(settings, user):
        others = sorted(
            n for n in db.known_editor_usernames(conn) if n != (user or "").lower()
        )
    return {
        # `switch_action` is the PAGE the form returns to -- never
        # request.url.path, which is /partials/sidebar when this context is
        # built for the 30s refresh.
        "switch_editors": others,
        "switch_action": f"/project/{current}" if current else "/",
        "acting_as": target if target and user
                     and target.lower() != user.lower() else None,
        "as_qs": _as_qs(request, target),
    }


@router.get("/partials/sidebar")
def partial_sidebar(request: Request, current: str = "", conn: sqlite3.Connection = Depends(get_conn)):
    return _render(request, "partials/sidebar.html", _sidebar_context(request, conn, current))


@router.get("/transfers")
def page_transfers(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    scope = auth.scope_for(request)
    transfers = build_transfers_view(conn, editor=scope.editor)
    return _render(request, "transfers.html", {
        **_sidebar_context(request, conn, None),
        "transfers": transfers,
        "safe_to_close": safe_to_close(transfers, scope.editor),
        "scope_admin": scope.admin,
        # Under Settings for an admin, and a top-level drawer entry for an
        # editor -- one value, partials/settings_nav.html decides which
        # entries that viewer is even shown.
        "nav_current": "transfers",
    })


@router.get("/partials/transfers")
def partial_transfers(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    scope = auth.scope_for(request)
    transfers = build_transfers_view(conn, editor=scope.editor)
    return _render(request, "partials/transfers.html", {
        "transfers": transfers,
        "safe_to_close": safe_to_close(transfers, scope.editor),
        "scope_admin": scope.admin,
    })


# --------------------------------------------- plan changes, and the undo
# DASH-8 (resilience sweep 2026-08-28). An untick with no `?machine=` removes
# a project from EVERY computer its editor owns, and until this panel the only
# record of it was the absence of a row. The window is short on purpose
# (db.PLAN_UNDO_WINDOW_SECONDS): an undo offered for yesterday's change is not
# an undo, it is a second decision taken with less information than the first.


# ------------------------------------------------------- server notices
#
# UX-10 (resilience sweep 2026-08-28). db.notice() is written beside the
# collector's and provision's own log lines; this is the half a
# non-technical owner can read. Admin-only: every one of these is a fact
# about the SERVER, and an editor can do nothing with it.

def _notices_context(conn, error: str | None = None) -> dict:
    open_rows = db.open_notices(conn)
    # DDIAG-8 (usability sweep 2026-09-03): the destination is a property of
    # the KIND, resolved here rather than in the template so the registry
    # stays the one place it is written down and a callable's failure cannot
    # reach Jinja.
    for row in open_rows:
        row["href"], row["href_label"] = db.notice_href(row.get("kind", ""),
                                                        row.get("subject", ""))
    # UX-6 (usability sweep 2026-09-03): the clean state used to read "Every
    # check below ran and found nothing wrong" over a panel that renders
    # [ NOT CHECKED ] for any kind nothing has ever evaluated, which is the
    # unchecked-reads-as-fine mistake wave 4 exists to end. Counted here
    # rather than in the template so the panel and its headline can never
    # disagree: same registry, same evidence set.
    kinds = db.notice_kinds()
    checked = set(db.notice_check_times(conn))
    ran = sum(1 for k in kinds if k["kind"] in checked)
    return {
        "notices": open_rows,
        "notice_error": error,
        # The registry, so an empty panel says WHAT was checked (owner,
        # 2026-08-28): silence must read as "checked and fine".
        "notice_kinds": kinds,
        "open_kinds": {row["kind"] for row in open_rows},
        # Finding 1 (resilience sweep 2026-08-28 fix pass): a registry entry
        # with no writer must render NOT CHECKED, never a false OK. Evidence,
        # not the registry itself -- see db.notice_check_times.
        "checked_kinds": checked,
        # UX-6: how many of the registry's kinds this build has actually
        # evaluated, and how many have never run.
        "notice_checks_ran": ran,
        "notice_checks_total": len(kinds),
        "notice_checks_never_ran": len(kinds) - ran,
    }


@router.get("/partials/notices")
def partial_notices(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "partials/notices.html", _notices_context(conn))


@router.post("/partials/notices/{notice_id}/dismiss")
def partial_notice_dismiss(
    notice_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """[ DISMISS ]: hide one notice until the condition is found again.

    Deliberately not a suppression: db.notice() reopens it on the next cycle
    that still sees the problem, so this clears a diagnosis that has been
    acted on and cannot silence a live one."""
    admin = _require_admin_page(request)
    row = db.dismiss_notice(conn, notice_id, admin)
    conn.commit()
    error = None if row else "that notice is already gone. Reload the page."
    return _render(request, "partials/notices.html", _notices_context(conn, error))


def _plan_changes_context(request: Request, conn, error: str | None = None,
                          notice: str | None = None) -> dict:
    return {
        "plan_changes": db.recent_plan_changes(conn, db.utcnow_iso()),
        "plan_error": error,
        "plan_notice": notice,
    }


@router.get("/partials/plan-changes")
def partial_plan_changes(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "partials/plan_changes.html",
                   _plan_changes_context(request, conn))


@router.post("/partials/plan-changes/{audit_id}/undo")
def partial_plan_change_undo(
    audit_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Put one tick or untick back exactly as it was.

    A RESTORE of the audit row's `before` placements, not an inverse action:
    the person-level untick that this exists for removed rows from several
    computers, each possibly in a different mode, and re-ticking "the project"
    would hand every one of them a full sync (docs/UPLOAD_ONLY_TICK.md). The
    undo is itself audited, and the enforce cycle leaves the restored rows
    alone for 60 s -- so an undo inside the window costs Syncthing nothing.
    """
    admin = _require_admin_page(request)
    entry = db.audit_entry(conn, audit_id)
    error = None
    notice = None
    if entry is None or entry["action"] not in (db.AUDIT_TICK, db.AUDIT_UNTICK):
        error = "that is not a plan change this page can undo"
    else:
        detail = entry["detail"] or {}
        editor = str(detail.get("editor") or "")
        slug = str(detail.get("slug") or entry["subject"] or "")
        before = detail.get("before") or []
        after = detail.get("after") or []
        try:
            age = (db.parse_iso(db.utcnow_iso()) - db.parse_iso(entry["at"])).total_seconds()
        except (ValueError, TypeError):
            # An unparseable (or offset-less, hence naive) stamp reads as
            # "now" rather than as an exception: the same rule the `ago`
            # filter learned in CR-89, and this page must render.
            age = 0.0
        if not editor or not slug:
            error = "that record does not name a project and an editor, so it cannot be undone"
        elif age > db.PLAN_UNDO_WINDOW_SECONDS:
            # Named, not silently refused: "nothing happened" is the one
            # answer a safety control must never give.
            error = ("that change is more than an hour old, so it is no longer offered "
                     "as an undo. Tick or untick it yourself if that is what you want.")
        else:
            now = db.utcnow_iso()
            keep = {str(row.get("machine") or "") for row in before}
            for row in after:
                machine = str(row.get("machine") or "")
                if machine not in keep:
                    db.remove_selection(conn, editor, slug, machine=machine)
            for row in before:
                db.add_selection(
                    conn, editor, slug, created_by=f"undo:{admin}", now=now,
                    machine=str(row.get("machine") or ""),
                    sync_mode=str(row.get("mode") or db.SYNC_MODE_FULL),
                )
            db.audit(conn, admin, db.AUDIT_PLAN_UNDO, slug, {
                "undid": int(audit_id), "undid_action": entry["action"],
                "editor": editor, "slug": slug, "restored": before,
            }, now=now)
            conn.commit()
            from .api import _nudge_collector

            _nudge_collector(request)
            notice = (f"put {slug} back for {editor}"
                      if before else f"removed {slug} again for {editor}")
    return _render(request, "partials/plan_changes.html",
                   _plan_changes_context(request, conn, error=error, notice=notice))


# ------------------------------------------------------ the fleet timeline
# SYS-11 (resilience sweep 2026-08-28). Every state-changing route writes one
# row to `fleet_audit`; this is where a human reads them back. It answers
# "what changed on Tuesday, and who did it" as a lookup, which is what CR-91a,
# CR-49 and CR-42 each cost a day of inference.


def _audit_context(request: Request, conn, query: str) -> dict:
    return {
        "audit_rows": db.fetch_audit(conn, limit=200, subject=query or None),
        "audit_query": query,
        "audit_max_age_days": db.AUDIT_MAX_AGE_DAYS,
    }


@router.get("/admin/audit")
def page_admin_audit(request: Request, q: str = "",
                     conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_audit.html", {
        **_sidebar_context(request, conn, None),
        **_audit_context(request, conn, q.strip()),
        "nav_current": "audit",
    })


@router.get("/partials/admin/audit")
def partial_admin_audit(request: Request, q: str = "",
                        conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "partials/admin_audit.html",
                   _audit_context(request, conn, q.strip()))


# ------------------------------------------------------------------- alerts
# SYS-8 (resilience sweep 2026-08-28). The page half of alerts.py: the same
# functions the JSON routes in api.py call, so a test send from here and one
# from a script behave identically. No secret is rendered by any of these:
# alerts.settings_view returns a mask and the value's source, never the value.


def _alerts_context(request: Request, conn, error: str = "",
                    notice: str = "") -> dict:
    from . import alerts

    settings = request.app.state.settings
    findings = alerts.scan(conn, settings, db.utcnow_iso())
    return {
        "alerts_settings": alerts.settings_view(conn, settings),
        "alerts_open": findings,
        "alerts_counts": alerts.open_counts(findings),
        "alerts_kinds": [{"kind": k.kind, "severity": k.severity,
                          "title": k.title, "what": k.what}
                         for k in alerts.ALERT_KINDS],
        "alerts_log": db.fetch_alerts(conn, limit=200),
        "alerts_interval_minutes": int(
            max(1.0, getattr(settings, "interval_alerts", 600.0)) // 60),
        "error": error,
        "notice": notice,
    }


@router.get("/admin/alerts")
def page_admin_alerts(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_alerts.html", {
        **_sidebar_context(request, conn, None),
        **_alerts_context(request, conn),
        "nav_current": "alerts",
    })


# -------------------------------------------------------------------- health
# SYS-6 (usability sweep 2026-09-03, wave 4). Four pages answered "is my fleet
# all right" and nothing composed them, so an owner who is not an engineer had
# no way to know which one was authoritative. This page is ONE ranked list
# over all four sources and NO NEW DATA: every row carries the diagnosis and
# the fix its own source already wrote, verbatim, and links to the page that
# owns it. If a sentence here reads badly, it reads badly on the detail page
# too, and that is where it gets fixed.
#
# The bands are severity, then source order. "Not checked" is its own band and
# never folds into OK (docs/SELF_DIAGNOSIS.md, the rule wave 4 of the 08-28
# sweep exists to hold): an unverified check is not a passing one.
HEALTH_BAND_ORDER = ("error", "warn", "unknown")
_HEALTH_SOURCE_ORDER = ("notice", "alert", "invariant", "protection")


def _health_rows(request: Request, conn) -> list[dict]:
    """Everything open, worst first. Never raises: this is the page an owner
    opens when something is already wrong, and one source that cannot answer
    must cost its own rows, not the page."""
    from . import alerts as alerts_mod
    from . import invariants as invariants_mod
    from . import protection as protection_mod

    settings = request.app.state.settings
    rows: list[dict] = []

    def add(**row) -> None:
        rows.append(row)

    try:
        # The registry's own sentence for the kind, so a row here reads the
        # same as the row on the notices panel rather than showing a raw key.
        kind_what = {k["kind"]: k.get("what", "") for k in db.notice_kinds()}
        for n in db.open_notices(conn):
            href, href_label = db.notice_href(n.get("kind", ""), n.get("subject", ""))
            add(source="notice", source_label="PROBLEM THE SERVER FOUND",
                band=("error" if n.get("severity") == "error" else "warn"),
                title=str(kind_what.get(n.get("kind"), "") or n.get("kind") or ""),
                subject=str(n.get("subject") or ""),
                diagnosis=str(n.get("body") or ""), fix=str(n.get("fix") or ""),
                href=href, href_label=href_label,
                detail_page="/#server-notices", detail_label="[ NOTICES ]")
    except Exception:  # noqa: BLE001 - see the docstring
        log.exception("health: could not read the open notices")

    try:
        for f in alerts_mod.scan(conn, settings, db.utcnow_iso()):
            add(source="alert", source_label="ALERT",
                band=("error" if f.get("severity") == "error" else "warn"),
                title=str(f.get("title") or ""), subject=str(f.get("subject") or ""),
                diagnosis=str(f.get("diagnosis") or ""), fix=str(f.get("fix") or ""),
                href="", href_label="",
                detail_page="/admin/alerts", detail_label="[ ALERTS ]")
    except Exception:  # noqa: BLE001
        log.exception("health: could not run the alert scan")

    try:
        for inv in invariants_mod.page_view(conn):
            state = inv.get("state")
            if state == db.INVARIANT_OK:
                continue
            band = ("unknown" if state in (db.INVARIANT_NOT_CHECKED,
                                           db.INVARIANT_CHECK_FAILED)
                    else ("error" if inv.get("severity") == "error" else "warn"))
            add(source="invariant", source_label="INVARIANT",
                band=band, title=str(inv.get("title") or ""),
                subject=str(inv.get("detail") or ""),
                diagnosis=str(inv.get("consequence") or ""),
                fix=str(inv.get("fix") or ""), href="", href_label="",
                detail_page="/admin/invariants", detail_label="[ INVARIANTS ]")
    except Exception:  # noqa: BLE001
        log.exception("health: could not read the invariants")

    try:
        for line in protection_mod.page_view(conn).get("lines", []):
            state = line.get("state")
            if state == protection_mod.OK:
                continue
            band = ("unknown" if state in (protection_mod.NOT_CHECKED,
                                           protection_mod.CHECK_FAILED)
                    else ("error" if line.get("severity") == "error" else "warn"))
            add(source="protection", source_label="PROTECTION",
                band=band, title=str(line.get("title") or ""),
                subject=str(line.get("detail") or ""),
                diagnosis=str(line.get("consequence") or ""),
                fix=str(line.get("fix") or ""), href="", href_label="",
                detail_page="/admin/protection", detail_label="[ PROTECTION ]")
    except Exception:  # noqa: BLE001
        log.exception("health: could not read the protection lines")

    rows.sort(key=lambda r: (HEALTH_BAND_ORDER.index(r["band"])
                             if r["band"] in HEALTH_BAND_ORDER else len(HEALTH_BAND_ORDER),
                             _HEALTH_SOURCE_ORDER.index(r["source"])
                             if r["source"] in _HEALTH_SOURCE_ORDER
                             else len(_HEALTH_SOURCE_ORDER),
                             r["title"], r["subject"]))
    return rows


def _health_context(request: Request, conn) -> dict:
    rows = _health_rows(request, conn)
    counts = {band: sum(1 for r in rows if r["band"] == band)
              for band in HEALTH_BAND_ORDER}
    # SYS-7 (usability sweep 2026-09-04): [ WHAT IS RUNNING ]. The dashboard
    # knows four of the drift doctor's five numbers and showed them on three
    # different pages with no verdict; a second customer has no base rig and
    # no repo, so for them the doctor does not exist. Read through
    # package_store.what_is_running, which is defensive line by line -- a box
    # that could 500 the HEALTH page would be a poor joke.
    try:
        running = package_store.what_is_running(
            conn, request.app.state.settings, request.app.state)
    except Exception:  # noqa: BLE001
        log.exception("could not build the WHAT IS RUNNING box")
        running = None
    return {"health_rows": rows, "health_counts": counts,
            "health_total": len(rows), "what_is_running": running}


@router.get("/admin/health")
def page_admin_health(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_health.html", {
        **_sidebar_context(request, conn, None),
        **_health_context(request, conn),
        "nav_current": "health",
    })


# ---------------------------------------------------------------- invariants
# SYS-9 (resilience sweep wave 5, 2026-08-29). READ-ONLY, and there is no
# button: this page names things, and every fix it names belongs to a page
# that already exists. A [ RE-CHECK NOW ] button was deliberately not added --
# the pass walks the tree and asks the NAS, and a page an admin can hammer is
# a page that can park the collector's single thread behind it.


@router.get("/admin/invariants")
def page_admin_invariants(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    from . import invariants

    settings = request.app.state.settings
    return _render(request, "admin_invariants.html", {
        **_sidebar_context(request, conn, None),
        "invariants": invariants.page_view(conn),
        "invariants_interval_minutes": int(
            max(1.0, getattr(settings, "interval_invariants", 900.0)) // 60),
        "nav_current": "invariants",
    })


# ---------------------------------------------------------------- protection
# SYS-14 (resilience sweep wave 5, 2026-08-29). What is protected, and what
# only looks protected. READ-ONLY except for the two dates nothing on this
# server can observe for itself (the release key's backup and a restore
# drill), which is why this page has forms at all -- and both of them write a
# DATE, never a boolean, so the lines above them can age.


def _protection_context(conn, error: str = "", notice: str = "") -> dict:
    from . import protection

    return {
        "protection": protection.page_view(conn),
        "protection_error": error,
        "protection_notice": notice,
    }


@router.get("/admin/protection")
def page_admin_protection(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_protection.html", {
        **_sidebar_context(request, conn, None),
        **_protection_context(conn),
        "nav_current": "protection",
    })


@router.post("/partials/admin/protection/ack")
async def partial_admin_protection_ack(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Record that a human did the thing this server cannot see.

    Audited like any other admin action: "somebody said the key was backed
    up" is exactly the kind of claim an incident review needs a name and a
    date against. A refusal (an unreadable or future date) is a message on
    the page, never a silently ignored click -- the failure mode of a
    swallowed acknowledgement is a line that reads MISSING for ever while the
    admin believes they cleared it.
    """
    admin = _require_admin_page(request)
    from . import protection

    form = await _form(request)
    error = ""
    notice = ""
    try:
        entry = protection.set_ack(conn, str(form.get("key") or ""),
                                   str(form.get("date") or ""), admin)
        db.audit(conn, admin, "protection.ack", str(form.get("key") or ""),
                 {"date": entry["date"]})
        conn.commit()
        notice = f"recorded {entry['date']}."
    except ValueError as exc:
        conn.rollback()
        error = str(exc)
    return _render(request, "partials/protection.html",
                   _protection_context(conn, error, notice))


# ------------------------------------------------------------------ recovery
# SYS-15 (resilience sweep wave 5, 2026-08-29). A WIZARD, NOT PROSE: it names
# what is protected right now, asks what went wrong, and either does the
# recovery or prints the exact commands with this customer's real pool name
# and platform in them. Where it cannot verify a fact it says so and prints
# NOTHING built on the guess -- a generated `zfs rollback` with the wrong
# dataset in it is worse than no command at all.


def _recovery_context(request: Request, conn, problem: str = "",
                      error: str = "", notice: str = "",
                      preview: dict | None = None,
                      result: dict | None = None) -> dict:
    from . import recovery

    return {
        "recovery": recovery.page_view(request.app.state.settings, conn, problem),
        "recovery_problem": problem,
        "recovery_error": error,
        "recovery_notice": notice,
        "recovery_preview": preview,
        "recovery_result": result,
    }


@router.get("/admin/recovery")
def page_admin_recovery(request: Request, problem: str = "",
                        conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_recovery.html", {
        **_sidebar_context(request, conn, None),
        **_recovery_context(request, conn, problem),
        "nav_current": "recovery",
    })


@router.post("/partials/admin/recovery/preview")
async def partial_admin_recovery_preview(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """What restoring this snapshot of this project would put back. READ
    ONLY: an owner choosing between two snapshots is asking "does the file I
    lost appear in this one", which is a list of names, not a date."""
    _require_admin_page(request)
    from . import recovery

    form = await _form(request)
    error, preview = "", None
    try:
        # REL-2's sweep (2026-09-04): a preview walks a whole snapshot of a
        # project on the NAS. Same rule as the publish above -- an `async`
        # route (it awaits the form) must not do filesystem work of unknown
        # length inside the event loop, because --workers 1 means everyone
        # else's request is behind it.
        preview = await run_in_threadpool(
            recovery.preview_restore,
            request.app.state.settings, conn, str(form.get("slug") or ""),
            str(form.get("snapshot") or ""))
    except recovery.RecoveryError as exc:
        error = str(exc)
    return _render(request, "partials/recovery.html",
                   _recovery_context(request, conn, str(form.get("problem") or ""),
                                     error, preview=preview))


@router.post("/partials/admin/recovery/restore")
async def partial_admin_recovery_restore(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Copy what is missing into `<project>/.restored-<ts>/`.

    There is no overwrite here and there is not going to be one: quarantine
    instead of overwrite is what makes the snapshot choice safe to get wrong,
    and it is the whole of SYS-15(a)."""
    admin = _require_admin_page(request)
    from . import recovery

    form = await _form(request)
    error, notice, result = "", "", None
    try:
        # REL-2's sweep (2026-09-04): this COPIES files, so it is the longest
        # blocking call on the page. Off the event loop.
        result = await run_in_threadpool(
            recovery.restore_into_quarantine,
            request.app.state.settings, conn, str(form.get("slug") or ""),
            str(form.get("snapshot") or ""), admin,
            include_changed=str(form.get("include_changed") or "") == "1")
        notice = (f"copied {result['files']} file(s) into {result['where']}. "
                  "Nothing that was already there was touched.")
    except recovery.RecoveryError as exc:
        conn.rollback()
        error = str(exc)
    return _render(request, "partials/recovery.html",
                   _recovery_context(request, conn, str(form.get("problem") or ""),
                                     error, notice, result=result))


@router.post("/partials/admin/recovery/drill")
async def partial_admin_recovery_drill(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Rehearse a restore (SYS-15d). A backup nobody has restored from is a
    hypothesis, and until this button existed nothing here had ever tried."""
    admin = _require_admin_page(request)
    from . import recovery

    form = await _form(request)
    error, notice = "", ""
    try:
        # REL-2's sweep (2026-09-04): a rehearsal restores real bytes. Same
        # rule as the two routes above.
        result = await run_in_threadpool(recovery.run_drill,
                                         request.app.state.settings, conn, admin)
        notice = (f"rehearsed a restore from {result['snapshot']}: {result['detail']}."
                  if result["ok"] else
                  f"the rehearsal FAILED: {result['detail']}.")
    except recovery.RecoveryError as exc:
        conn.rollback()
        error = str(exc)
    return _render(request, "partials/recovery.html",
                   _recovery_context(request, conn, str(form.get("problem") or ""),
                                     error, notice))


@router.get("/admin/alerts/preview", response_class=PlainTextResponse)
def page_admin_alerts_preview(request: Request,
                              conn: sqlite3.Connection = Depends(get_conn)):
    """This week's report exactly as it would be sent. Text, not a rendered
    page: the thing being previewed IS the text."""
    _require_admin_page(request)
    from . import alerts

    subject, text = alerts.compose_weekly(conn, db.utcnow_iso(),
                                          request.app.state.settings)
    return PlainTextResponse(f"Subject: {subject}\n\n{text}")


@router.post("/partials/admin/alerts/save")
async def partial_admin_alerts_save(request: Request,
                                    conn: sqlite3.Connection = Depends(get_conn)):
    user = _require_admin_page(request)
    from . import alerts

    form = await _form(request)
    values = {k: v for k, v in form.items() if k in alerts.SETTING_KEYS}
    error = ""
    notice = ""
    # DDIAG-4 (2026-09-04): the sink BEFORE the save, so the page can promise
    # the one thing an admin who has just switched mail on is waiting for.
    # Everything open today was recorded undelivered while there was no
    # channel, and alerts.set_settings re-opens it.
    before = alerts.get_settings(conn).get("alerts_sink") or alerts.SINK_NONE
    try:
        saved = alerts.set_settings(conn, values, user)
        db.audit(conn, user, "alerts.settings", "alerts",
                 {"sink": values.get("alerts_sink", "")})
        conn.commit()
        turned_on = (before == alerts.SINK_NONE
                     and (saved.get("alerts_sink") or before) != alerts.SINK_NONE)
        notice = ("Saved. The next check will send everything that is "
                  "currently open." if turned_on else "saved.")
    except alerts.AlertError as exc:
        conn.rollback()
        error = str(exc)
    return _render(request, "partials/admin_alerts.html",
                   _alerts_context(request, conn, error, notice))


@router.post("/partials/admin/alerts/password")
async def partial_admin_alerts_password(request: Request,
                                        conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    from . import alerts

    form = await _form(request)
    settings = request.app.state.settings
    error = ""
    notice = ""
    try:
        if form.get("clear") == "1":
            notice = ("password cleared." if alerts.clear_password(settings)
                      else "there was no stored password.")
        else:
            alerts.set_password(settings, form.get("password", ""))
            notice = "password stored."
    except alerts.AlertError as exc:
        error = str(exc)
    return _render(request, "partials/admin_alerts.html",
                   _alerts_context(request, conn, error, notice))


@router.post("/partials/admin/alerts/test")
def partial_admin_alerts_test(request: Request,
                              conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    from . import alerts

    subject, text = alerts.compose_alert(
        alerts.KIND_TEST, "test",
        "This is a test of the CC Sync alert channel. Nothing is wrong.")
    # dedup OFF: an admin pressing the button twice is asking twice, and a
    # silent "already sent today" is exactly the answer that makes somebody
    # believe a broken sink works.
    result = alerts.send(conn, request.app.state.settings, subject, text,
                         kind=alerts.KIND_TEST, dedup=False)
    conn.commit()
    if result["ok"]:
        notice = f"test sent to {result['sent_to'] or 'the configured sink'}."
        error = ""
    else:
        notice = ""
        error = f"the test could not be sent: {result['detail']}"
    return _render(request, "partials/admin_alerts.html",
                   _alerts_context(request, conn, error, notice))


@router.get("/partials/project/{slug}/bins")
def partial_bins(slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    scope = auth.scope_for(request)
    view = build_presence_view(conn, slug, editor=scope.editor)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    return _render(request, "partials/bins.html", {"presence": view, "scope_admin": scope.admin})


@router.get("/partials/fleet")
def partial_fleet(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    scope = auth.scope_for(request)
    return _render(request, "partials/fleet_grid.html", {
        "view": api_scope_projects_view(build_projects_view(conn), scope),
        "fleet": api_scope_editors_view(build_editors_view(conn), scope),
    })


@router.get("/partials/project/{slug}")
def partial_project(slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    tick_editor = _queue_editor(request)
    return _render(request, "partials/project_detail.html", {
        "project": view,
        "selected_by": db.fetch_all_selections(conn),
        "selected_modes": db.fetch_all_selection_modes(conn),
        "moves": db.file_moves_for_project(conn, slug),
        "move_projects": [dict(r) for r in conn.execute(
            "SELECT slug, label FROM projects WHERE active=1 ORDER BY label")],
        # DCORE-16 (usability sweep 2026-09-04): the config/enforce cycles
        # that did not do everything they described. This is the page where
        # somebody asks why a computer is not getting THIS project, and "a
        # sharing change is held" was recorded, alerted on, and rendered
        # nowhere near the question. Empty is the normal state and renders as
        # nothing.
        "enforce_notes": db.enforce_notes(conn),
        "tick_editor": tick_editor,
        # UX-12 / DASH-8 (2026-08-28): the person's computers, so this render
        # carries the same person-level untick confirm and the same
        # [ TICK FOR ALL OF ...'S COMPUTERS (N) ] label as the full page.
        "toggle_editor_machines": db.machines_of(conn, tick_editor) if tick_editor else [],
        "as_qs": _as_qs(request, tick_editor),
    })


async def _partial_project_link_edit(
    slug: str, request: Request, conn: sqlite3.Connection, action: str,
):
    """Add or remove a shared-folder link from the project page
    (SHARED_FOLDERS_PLAN.md WP5). Same auth rule as the JSON endpoints;
    refusals come back as a banner in the re-rendered detail, not a dead
    htmx swap."""
    from .api import (add_project_link, remove_project_link,
                      _require_link_write)

    settings = request.app.state.settings
    form = await _form(request)
    path = form.get("path", "").strip()
    error = None
    try:
        _require_link_write(request, conn, slug)
        if not path:
            error = "type or paste the folder to share (e.g. 2026/FF5/Elections/Interviewees/...)"
        elif action == "add":
            add_project_link(settings, conn, slug, path, auth.get_session_user(request) or "")
        else:
            remove_project_link(settings, conn, slug, path, auth.get_session_user(request) or "")
    except HTTPException as exc:
        error = str(exc.detail)
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    tick_editor = _queue_editor(request)
    return _render(request, "partials/project_detail.html", {
        "project": view,
        "selected_by": db.fetch_all_selections(conn),
        "selected_modes": db.fetch_all_selection_modes(conn),
        "moves": db.file_moves_for_project(conn, slug),
        "tick_editor": tick_editor,
        "as_qs": _as_qs(request, tick_editor),
        "link_error": error,
    })


@router.post("/partials/project/{slug}/move")
async def partial_project_move(slug: str, request: Request,
                               conn: sqlite3.Connection = Depends(get_conn)):
    """The [ MOVE ON THE SERVER AND ON EVERY MACHINE ] form (docs/FILE_MOVES.md).
    Same shape as the link edit: refusals come back as a banner in the
    re-rendered detail, never a dead htmx swap."""
    from .api import FileMoveIn, _require_move_write, move_project_files

    settings = request.app.state.settings
    form = await _form(request)
    error = None
    done = None
    try:
        user = _require_move_write(request)
        path = form.get("path", "").strip()
        if not path:
            error = "type the file or folder to move, e.g. B-roll/A001_0512.braw"
        else:
            body = FileMoveIn(path=path, to_slug=(form.get("to_slug", "").strip() or None),
                              to_path=form.get("to_path", ""))
            done = move_project_files(settings, conn, slug, body, user)
    except HTTPException as exc:
        error = str(exc.detail)
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    tick_editor = _queue_editor(request)
    return _render(request, "partials/project_detail.html", {
        "project": view,
        "selected_by": db.fetch_all_selections(conn),
        "selected_modes": db.fetch_all_selection_modes(conn),
        "moves": db.file_moves_for_project(conn, slug),
        "move_projects": [dict(r) for r in conn.execute(
            "SELECT slug, label FROM projects WHERE active=1 ORDER BY label")],
        # DCORE-16 (usability sweep 2026-09-04): the config/enforce cycles
        # that did not do everything they described. This is the page where
        # somebody asks why a computer is not getting THIS project, and "a
        # sharing change is held" was recorded, alerted on, and rendered
        # nowhere near the question. Empty is the normal state and renders as
        # nothing.
        "enforce_notes": db.enforce_notes(conn),
        "tick_editor": tick_editor,
        "as_qs": _as_qs(request, tick_editor),
        "move_error": error,
        "move_done": done,
    })


def _rendered_project_detail(request, conn, slug: str, *, error=None, done=None):
    """The project detail fragment, the way partial_project_move renders it.
    Shared by the two move buttons below so a refusal is a banner in the page
    rather than a dead htmx swap."""
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    tick_editor = _queue_editor(request)
    return _render(request, "partials/project_detail.html", {
        "project": view,
        "selected_by": db.fetch_all_selections(conn),
        "selected_modes": db.fetch_all_selection_modes(conn),
        "moves": db.file_moves_for_project(conn, slug),
        "move_projects": [dict(r) for r in conn.execute(
            "SELECT slug, label FROM projects WHERE active=1 ORDER BY label")],
        # DCORE-16 (usability sweep 2026-09-04): the config/enforce cycles
        # that did not do everything they described. This is the page where
        # somebody asks why a computer is not getting THIS project, and "a
        # sharing change is held" was recorded, alerted on, and rendered
        # nowhere near the question. Empty is the normal state and renders as
        # nothing.
        "enforce_notes": db.enforce_notes(conn),
        "tick_editor": tick_editor,
        "as_qs": _as_qs(request, tick_editor),
        "move_error": error,
        "move_done": done,
    })


@router.post("/partials/project/{slug}/moves/{move_id}/undo")
async def partial_project_move_undo(slug: str, move_id: int, request: Request,
                                    conn: sqlite3.Connection = Depends(get_conn)):
    """[ UNDO THIS MOVE ] (UX-11, resilience sweep 2026-08-28): the inverse
    move through the same machinery that made the original."""
    from .api import _require_move_write, undo_file_move

    error = None
    done = None
    try:
        user = _require_move_write(request)
        done = undo_file_move(request.app.state.settings, conn, slug, move_id, user)
    except HTTPException as exc:
        error = str(exc.detail)
    return _rendered_project_detail(request, conn, slug, error=error, done=done)


@router.post("/partials/project/{slug}/moves/{move_id}/reissue")
async def partial_project_move_reissue(slug: str, move_id: int, request: Request,
                                       conn: sqlite3.Connection = Depends(get_conn)):
    """[ ASK THAT COMPUTER AGAIN ] (DASH-9): put an expired move back in that
    machine's queue, instead of the silence that let it re-upload the old
    path."""
    from .api import _require_move_write

    form = await _form(request)
    error = None
    try:
        user = _require_move_write(request)
        ok = db.reissue_file_move(conn, move_id, form.get("editor", "").strip().lower(),
                                  form.get("machine", "").strip(), db.utcnow_iso(),
                                  actor=user)
        conn.commit()
        if not ok:
            error = "that computer has already answered this move"
    except HTTPException as exc:
        error = str(exc.detail)
    return _rendered_project_detail(request, conn, slug, error=error)


@router.post("/partials/project/{slug}/links")
async def partial_project_link_add(
    slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    return await _partial_project_link_edit(slug, request, conn, "add")


@router.post("/partials/project/{slug}/links/remove")
async def partial_project_link_remove(
    slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    return await _partial_project_link_edit(slug, request, conn, "remove")


@router.get("/partials/project/{slug}/missing/{device_id}")
def partial_missing(
    slug: str, device_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    project = db.fetch_project(conn, slug)
    if project is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    editor = next((e for e in project["editors"] if e["device_id"] == device_id), None)
    if editor is None:
        raise HTTPException(status_code=404, detail=f"device not in project: {device_id}")
    # The file paths missing from a named person's machine. Same rule (and the
    # same 404, so no device id is confirmed) as the JSON twin api_missing.
    if not auth.scope_for(request).allows(str(editor.get("editor_username") or "")):
        raise HTTPException(status_code=404, detail=f"device not in project: {device_id}")
    missing = db.fetch_missing(conn, project["id"], editor["device_row_id"])
    return _render(request, "partials/missing_files.html", {
        "missing": missing,
        "need_items": editor["need_items"],
        "editor_label": editor["editor_username"] or editor["name"],
    })


# ------------------------------------------------------------- admin users

def _require_admin_page(request: Request) -> str:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None or not auth.is_admin(settings, user):
        raise HTTPException(status_code=403 if user else 401, detail="admins only")
    return user


async def _form(request: Request) -> dict[str, str]:
    """Parse an htmx form body. The BYTE ceiling is app.py's body_size_gate
    (every write path, not just the two it used to cover -- DASH-3); the field
    ceiling is here, because 1 MB of `a=1&a=1&...` is a cheap way to spend the
    single worker's CPU inside parse_qs. page_login_submit has capped its
    fields since it was written; these routes never did (2026-08-11)."""
    try:
        parsed = parse_qs((await request.body()).decode(), max_num_fields=MAX_FORM_FIELDS)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed form body")
    return {k: v[0] for k, v in parsed.items()}


@router.get("/admin/users")
def page_admin_users(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_users.html", {
        **_sidebar_context(request, conn, None),
        "admin_users": build_admin_users_view(request.app.state.settings, conn),
        # No packages context here since 2026-08-18: the packages table, the
        # vendor feed and the dashboard update were the bottom third of this
        # page and are page_admin_packages() now.
        "nav_current": "users",
    })


@router.get("/partials/admin/users")
def partial_admin_users(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(request.app.state.settings, conn),
    })


# ------------------------------------------------- admin: browser sessions
# A separate partial and a separate route from the Users panel above, loaded by
# admin_users.html with its own hx-get. Kept apart deliberately: the Users panel
# talks to the NAS and goes amber the moment the NAS blinks (DASH-7), and
# "revoke this person's sessions" -- the thing an admin reaches for when a
# laptop goes missing -- must keep working while that is happening.

def _sessions_context(request: Request, error: str | None = None) -> dict:
    store = auth.session_store(request)
    rows = store.list_all() if store is not None else []
    for row in rows:
        # A prefix only: the full sid is a keyed digest of the cookie, and
        # while it cannot be replayed, there is no reason to print it.
        row["short_sid"] = row["sid"][:12]
    return {"sessions": rows, "error": error,
            "session_user": auth.get_session_user(request)}


@router.get("/partials/admin/sessions")
def partial_admin_sessions(request: Request):
    _require_admin_page(request)
    return _render(request, "partials/admin_sessions.html", _sessions_context(request))


@router.post("/partials/admin/sessions/revoke")
async def partial_admin_revoke_sessions(request: Request):
    """Sign somebody out everywhere. The revocation is what makes a stolen
    cookie recoverable at all -- before 2026-08-17 the only answer was to
    rotate DASH_SESSION_SECRET, which signs out the entire fleet and
    invalidates every companion identity token with it."""
    admin = _require_admin_page(request)
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    error = None
    store = auth.session_store(request)
    if not username:
        error = "username required"
    elif store is None:
        error = "sessions are not being recorded on this deployment"
    else:
        revoked = store.revoke_user(username, by=f"admin:{admin}")
        log.warning("admin %r revoked %d session(s) for %r", admin, revoked, username)
        error = f"revoked {revoked} session(s) for {username}"
    return _render(request, "partials/admin_sessions.html",
                   _sessions_context(request, error))


def _create_or_update_editor_sync(
    nas: NasBackend, username: str, ssh_pubkey: str,
    full_name: str | None, password: str | None,
) -> dict:
    """Runs on a threadpool worker -- see partial_admin_create_user. The
    TrueNAS backend's job polling (_wait_for_job) blocks on time.sleep() for
    up to ~2 minutes."""
    result = nas.create_or_update_editor(username, ssh_pubkey, full_name)
    if password:
        nas.set_known_password(username, password)
    return result


@router.post("/partials/admin/users/create")
async def partial_admin_create_user(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    ssh_pubkey = form.get("ssh_pubkey", "").strip()
    full_name = form.get("full_name", "").strip() or None
    password = form.get("password", "").strip() or None

    if str(settings.auth_method or "smb").strip().lower() == "local":
        # No NAS account of any kind (WP C, docs/ZERO_TOUCH_PLAN.md §3.3,
        # 2026-08-17): the same form posts here, but username/password/role
        # go into the local `users` table instead. A blank password field
        # generates a one-time one, shown back to the admin exactly once.
        role = form.get("role", "editor").strip().lower() or "editor"
        generated = None
        minted = password
        if not minted:
            minted = secrets.token_urlsafe(15)
            generated = minted
        error = None
        try:
            local_users.create_user(conn, username, minted, role, created_by=admin)
            if ssh_pubkey:
                local_users.add_ssh_key(conn, username, ssh_pubkey)
        except local_users.LocalUserError as exc:
            error = str(exc)
        else:
            db.record_known_editor(conn, username, "admin")
            conn.commit()
        # DUI-1 (2026-09-04): a generated password used to come back through
        # the `error` key, so the one success an admin must transcribe wore
        # the warning triangle -- and it was painted INSIDE this panel, which
        # admin_users.html re-fetches every 30 s. The next poll swapped the
        # credential away for good and there was no [ COPY ] button. It is an
        # out-of-band swap into #minted-secret now: an element outside every
        # polling wrapper on the page. Never `error`, never in this panel.
        return _render(request, "partials/admin_users.html", {
            "admin_users": build_admin_users_view(settings, conn),
            "error": error,
            "minted_secret": generated if error is None else None,
            "minted_kind": "password",
            "minted_username": username,
        })

    error = None
    if not nas_factory.nas_configured(settings):
        # UX-13 (2026-09-04): the NEW name first, and the two places an owner
        # can actually set it. The old text named TRUENAS_PW and asked for a
        # redeploy, which is the one thing a non-technical owner cannot do.
        error = ("This dashboard has no NAS password, so editor accounts cannot be "
                 "created here. Set it on Settings, Setup (Connect to your NAS), or set "
                 "DASH_NAS_PW in the container.")
    elif not is_valid_username(username):
        error = ("username must start with a letter and contain only lowercase letters, "
                 "digits, '.', '_', '-'")
    elif ssh_pubkey and not looks_like_ssh_pubkey(ssh_pubkey):
        error = "does not look like an OpenSSH public key"
    elif not ssh_pubkey and api_blank_key_refusal(request, username):
        # OPS-2 / UX-14: blank is allowed for a NEW account and refused for
        # an existing one, because both NAS backends write the key they are
        # handed and a blank one erases the key that account's lanes are
        # using. [ UPDATE SSH KEY ] on a row posts here with a real key, so
        # it never reaches this branch.
        error = api_blank_key_refusal(request, username)
    elif password and auth.check_password(password):
        # Optional field: blank still means "randomise it, no dashboard login".
        # A SHORT one is refused -- same floor as the set-password form.
        error = auth.check_password(password)
    else:
        try:
            nas = nas_factory.make_nas_client(settings)
            # Blocking NAS REST calls + job polling -- push off the event
            # loop so a slow NAS response can't stall every other
            # request for up to ~2 minutes (see the ui.py blocking-handlers
            # finding).
            result = await run_in_threadpool(
                _create_or_update_editor_sync, nas, username, ssh_pubkey, full_name, password
            )
            # The account provably exists now -- record it so a device named
            # after it is treated as an editor rather than as an unmapped
            # machine (B16). The JSON API twin has done this since the B16 fix;
            # THIS is the route the Users page posts to, and it did not, so an
            # editor created through the UI got no known_editors row and
            # enforce shared them nothing (KNOWN_BUGS DASH-2, 2026-08-11).
            db.record_known_editor(conn, username, "admin")
            conn.commit()
            if result["warnings"]:
                error = f"{username}: created with warnings ({'; '.join(result['warnings'])})"
        except NasError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/password")
async def partial_admin_set_password(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    password = form.get("password", "").strip()

    # DUI-18 (2026-09-04): [ SET ] answered with an empty banner slot, so a
    # write that locks somebody out of the dashboard looked identical to a
    # click that did nothing. It gets a result line of its own -- `notice`,
    # not `error`, which the panel already renders without the triangle.
    done = f"Password set for {username}. Tell them the new password: it is not shown here again."

    if str(settings.auth_method or "smb").strip().lower() == "local":
        error = None
        notice = None
        if not password:
            error = "password required"
        else:
            try:
                local_users.set_password(conn, username, password)
            except local_users.LocalUserError as exc:
                error = str(exc)
            else:
                conn.commit()
                notice = done
        return _render(request, "partials/admin_users.html", {
            "admin_users": build_admin_users_view(settings, conn),
            "error": error,
            "notice": notice,
        })

    error = None
    notice = None
    if not nas_factory.nas_configured(settings):
        error = "DASH_NAS_PW is not configured on the dashboard"
    elif not is_valid_username(username):
        # Same charset gate as the create form: a typo (or a hand-posted
        # "root") must never reach the NAS. set_known_password refuses system
        # and non-editor accounts too -- this is the cheap first pass.
        error = ("username must start with a letter and contain only lowercase letters, "
                 "digits, '.', '_', '-'")
    elif not password:
        error = "password required"
    elif auth.check_password(password):
        # Floor on NEW passwords only (auth.MIN_PASSWORD_CHARS): the minimum
        # used to be one character, and this password is what an editor signs
        # into the dashboard with AND their NAS/SMB credential. Existing short
        # passwords keep working -- nobody is locked out mid-shoot
        # (2026-08-17, COMMERCIAL_READINESS.md item 15, L-tier "admin password
        # min length 1").
        error = auth.check_password(password)
    else:
        try:
            nas = nas_factory.make_nas_client(settings)
            # See the ui.py blocking-handlers finding: blocking NAS call
            # off the event loop.
            await run_in_threadpool(nas.set_known_password, username, password)
        except NasError as exc:
            error = str(exc)
        else:
            notice = done

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
        "notice": notice,
    })


@router.post("/partials/admin/users/approve")
async def partial_admin_approve_device(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    device_id = form.get("device_id", "").strip()
    username = form.get("username", "").strip().lower()
    # An unchecked HTML checkbox is simply absent from the form body, so the
    # default is the safe one without a falsy-string dance.
    create_new = form.get("create_new", "") != ""

    error = None
    if not settings.syncthing_url:
        error = "SYNCTHING_GUI_URL is not configured"
    elif not is_valid_username(username):
        error = "username must be a valid TrueNAS-style username"
    else:
        try:
            # Shape-check + uppercase BEFORE Syncthing sees it, as the JSON API
            # twin has since _DEVICE_ID_RE was added. This partial -- the only
            # approve path a human uses -- skipped it, so a truncated or
            # lowercased paste came back as a generic 502, or created a device
            # that can never connect (KNOWN_BUGS DASH-1, 2026-08-11).
            device_id = normalize_device_id(device_id)
            # After the shape check on purpose: a truncated paste must still
            # report the DASH-1 message rather than be masked by this one.
            # The human path into the B16 shape, since the machine name is
            # printed in the column beside the box (CR-91). Same guard, same
            # wording as the JSON twin.
            unknown = approve_username_error(conn, username, create_new)
            if unknown:
                raise ValueError(unknown)
            syncthing = SyncthingClient.from_settings(settings)
            # See the ui.py blocking-handlers finding: blocking Syncthing
            # REST call off the event loop.
            await run_in_threadpool(syncthing.approve_device, device_id, username)
            # An admin naming the device is the strongest evidence the username
            # is a real editor account (B16 / DASH-2).
            db.record_known_editor(conn, username, "admin")
            conn.commit()
        except ValueError as exc:
            error = str(exc)
        except SyncthingError as exc:
            error = str(exc)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/disable")
async def partial_admin_disable_user(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Disable (or re-enable) a LOCAL account -- there is no NAS twin of this
    in scope here, same carve-out as api.api_admin_disable_user.

    Same guards and the same credential purge as that route (dash-admin-5,
    2026-08-21): this button called `local_users.disable_user` bare, so the
    Users page could disable the last enabled admin -- or the admin's own
    account -- that the JSON route refuses, and left the disabled account's
    sessions and report token live. "The button on the Users page must not be
    a softer door than the JSON route" (partial_admin_delete_user)."""
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    disabled = form.get("disabled", "1").strip() != "0"

    error = None
    if str(settings.auth_method or "smb").strip().lower() != "local":
        error = "this action is only available with DASH_AUTH_METHOD=local"
    else:
        try:
            local_users.disable_user(conn, username, disabled, requested_by=admin)
        except local_users.LocalUserError as exc:
            error = str(exc)
        else:
            conn.commit()
            if disabled:
                # AFTER the commit, for the deadlock reason api's own route
                # documents: the purge writes through the session store's own
                # connection to this same SQLite file.
                api_purge_user_credentials(request, conn, username, by=admin,
                                           why="account disabled")
                conn.commit()   # the token half of the purge writes on `conn`

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/projects/archive")
async def partial_admin_archive_project(request: Request,
                                        conn: sqlite3.Connection = Depends(get_conn)):
    """[ ARCHIVE PROJECT ] / [ UNARCHIVE ] on the SYNC PLANS page (DCORE-5).

    A plain form and a redirect, not an htmx swap: this page is a grid whose
    every row changes when a project leaves it, and re-rendering the whole
    page is what the reader expects to see. The confirm (which names how many
    editors still sync it) is the form's own, the way the topbar's sign-out-
    everywhere does it -- see partials/topbar.html.

    Nothing here deletes: the folder, its marker, its files and every tick
    stay exactly where they are."""
    admin = _require_admin_page(request)
    form = await _form(request)
    slug = form.get("slug", "").strip()
    archived = form.get("archived", "1").strip() != "0"
    if slug:
        if archived:
            if db.archive_project(conn, slug, by=admin):
                db.audit(conn, admin, "project.archive", slug,
                         {"editors": db.project_tick_editors(conn, slug)})
                log.warning("admin %r archived project %r from the plans page: nothing "
                            "was deleted and its shares go on the next enforce cycle",
                            admin, slug)
        elif db.unarchive_project(conn, slug):
            db.audit(conn, admin, "project.unarchive", slug, {})
        conn.commit()
    return RedirectResponse("/admin/assignments", status_code=303)


@router.post("/partials/admin/users/suspend")
async def partial_admin_suspend_user(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Pause (or resume) an editor's whole fleet access (DCORE-4, 2026-09-04).

    NOT local-mode gated, unlike DISABLE beside it: this acts on fleet state,
    so it is the "stop this person" button an smb site has instead of DELETE.
    Same guards as the JSON route, which is why it goes through it."""
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    suspended = form.get("suspended", "1").strip() != "0"
    reason = form.get("reason", "").strip()[:255]

    error = None
    notice = None
    if not is_valid_username(username):
        error = "not a valid username"
    elif suspended and username == admin.strip().lower():
        error = ("you cannot suspend the account you are signed in as - sign in as "
                 "another admin to suspend this one")
    elif suspended:
        if db.suspend_editor(conn, username, by=admin, reason=reason):
            db.audit(conn, admin, "user.suspend", username, {"reason": reason})
            conn.commit()
            notice = (f"{username} is suspended. Their computers are being turned away "
                      "and their projects will be unshared within a minute. The sync "
                      "plan is untouched: RESUME puts it all back.")
            log.warning("admin %r suspended %r from the Users page", admin, username)
        else:
            error = f"{username} is not an editor this dashboard knows"
    else:
        db.unsuspend_editor(conn, username)
        db.audit(conn, admin, "user.resume", username, {})
        conn.commit()
        notice = (f"{username} is back. Their projects are shared again on the next "
                  "cycle, exactly as they were.")
        log.warning("admin %r resumed %r from the Users page", admin, username)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
        "notice": notice,
    })


@router.post("/partials/admin/users/keys/approve")
async def partial_admin_approve_ssh_key(request: Request,
                                        conn: sqlite3.Connection = Depends(get_conn)):
    """Install a key an editor's wizard offered (OPS-2). One click, the same
    implementation the JSON route uses; a refusal is this panel's banner
    because htmx swaps the response either way."""
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    fingerprint = form.get("fingerprint", "").strip()

    error = None
    notice = None
    try:
        await run_in_threadpool(
            api_approve_pending_ssh_key, request, conn, username, fingerprint, admin=admin)
    except HTTPException as exc:
        error = str(exc.detail)
    else:
        notice = (f"SSH key added for {username}. Their upload and proxy download can "
                  "authenticate now.")

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
        "notice": notice,
    })


@router.post("/partials/admin/users/keys/dismiss")
async def partial_admin_dismiss_ssh_key(request: Request,
                                        conn: sqlite3.Connection = Depends(get_conn)):
    """Throw an offered key away. Nothing is revoked: that computer still has
    the private half and offers it again on its next sign-in."""
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    fingerprint = form.get("fingerprint", "").strip()
    if db.drop_pending_ssh_key(conn, username, fingerprint):
        db.audit(conn, admin, "ssh_key.dismiss", username, {"fingerprint": fingerprint})
    conn.commit()
    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
    })


@router.post("/partials/admin/users/delete")
async def partial_admin_delete_user(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Delete a user everywhere (CR-76): the same implementation as
    DELETE /api/v1/admin/users/{username} -- the button on the Users page
    must not be a softer door than the JSON route. Refusals and backend
    failures come back as this partial's banner rather than an HTTP error,
    because htmx swaps the response in either case and an admin needs to
    READ why it refused (and what, if anything, was done)."""
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()

    error = None
    notice = None
    try:
        result = delete_user_everywhere(request, conn, username, admin=admin)
    except HTTPException as exc:
        error = str(exc.detail)
    else:
        if result["warnings"]:
            notice = f"deleted {username}: " + "; ".join(result["warnings"])

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
        "notice": notice,
    })


@router.post("/partials/admin/machines/forget")
async def partial_admin_forget_machine(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Remove one computer from the fleet (CR-76), from the Users page's
    [ COMPUTERS ] table. Same implementation as
    DELETE /api/v1/admin/machines/{editor}/{machine}; a refusal is the
    partial's banner."""
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    editor = form.get("editor", "").strip().lower()
    machine = form.get("machine", "").strip()

    error = None
    try:
        forget_machine_everywhere(request, conn, editor, machine, admin=admin)
    except HTTPException as exc:
        error = str(exc.detail)

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/keys/add")
async def partial_admin_add_ssh_key(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    key_text = form.get("key_text", "").strip()
    label = form.get("label", "").strip()

    error = None
    if str(settings.auth_method or "smb").strip().lower() != "local":
        error = "this action is only available with DASH_AUTH_METHOD=local"
    else:
        try:
            local_users.add_ssh_key(conn, username, key_text, label=label)
        except local_users.LocalUserError as exc:
            error = str(exc)
        else:
            conn.commit()

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


@router.post("/partials/admin/users/keys/remove")
async def partial_admin_remove_ssh_key(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    fingerprint = form.get("fingerprint", "").strip()

    error = None
    if str(settings.auth_method or "smb").strip().lower() != "local":
        error = "this action is only available with DASH_AUTH_METHOD=local"
    else:
        local_users.remove_ssh_key(conn, username, fingerprint)
        conn.commit()

    return _render(request, "partials/admin_users.html", {
        "admin_users": build_admin_users_view(settings, conn),
        "error": error,
    })


# ------------------------------------------------- per-editor report tokens
#
# COMMERCIAL_READINESS.md item 15 (2026-08-17). Its own panel and its own
# routes rather than fields bolted onto the Users partial: that partial's
# render calls a NAS backend, and minting a fleet credential must not be able
# to fail because the NAS is slow. The secret is rendered exactly once, in the
# response to the mint -- nothing stores it, so no later render can repeat it.

def _report_tokens_render(request, conn, *, error: str | None = None,
                          minted: str | None = None, minted_username: str = ""):
    # DUI-1 (2026-09-04): the token itself leaves this panel. It used to be a
    # banner inside a box that admin_users.html re-fetches every 60 s, so the
    # one value the dashboard will never be able to show again had a lifetime
    # of under a minute and no [ COPY ] control. It goes out of band into
    # #minted-secret now, which no poll targets.
    return _render(request, "partials/admin_report_tokens.html", {
        "report_tokens": build_report_tokens_view(conn),
        "error": error,
        "minted_secret": minted,
        "minted_kind": "token",
        "minted_username": minted_username,
    })


@router.get("/partials/admin/report-tokens")
def partial_admin_report_tokens(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    return _report_tokens_render(request, conn)


@router.post("/partials/admin/report-tokens/create")
async def partial_admin_create_report_token(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    form = await _form(request)
    username = form.get("username", "").strip().lower()
    label = form.get("label", "").strip()
    if not is_valid_username(username):
        return _report_tokens_render(
            request, conn,
            error=("username must start with a letter and contain only lowercase "
                   "letters, digits, '.', '_', '-'"))
    token, _row = db.create_editor_report_token(conn, username, created_by=admin,
                                                label=label)
    conn.commit()
    return _report_tokens_render(request, conn, minted=token, minted_username=username)


@router.post("/partials/admin/report-tokens/revoke")
async def partial_admin_revoke_report_token(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    form = await _form(request)
    revoked = db.revoke_editor_report_token(conn, form.get("token_id", "").strip(),
                                            revoked_by=admin)
    conn.commit()
    error = None if revoked else "that token was already revoked (or never existed)"
    return _report_tokens_render(request, conn, error=error)


# ------------------------------------------------------------- fleet halt
#
# COMMERCIAL_READINESS.md item 9 (2026-08-17). One switch that stops every
# companion in the fleet, honoured on each machine's next report reply. It
# lives on the Users page rather than the fleet grid deliberately: this is an
# administrative control with a blast radius of the whole company, and the
# fleet grid is a page people leave open and click around on.
#
# The route is a thin wrapper over the same db helpers /api/v1/fleet/halt
# uses, so the button and the API can never disagree about what is stored.

def _halt_banner_context(conn) -> dict:
    """The standing banner's numbers: how long, and how many computers.

    "Machines in the fleet" is the registry count, not the ones reporting
    right now: a halt reaches a machine on its NEXT report, so one that is
    switched off is affected too."""
    now = db.utcnow_iso()
    halt = db.get_fleet_halt(conn, now=now)
    hours = 0
    if halt["set_at"]:
        try:
            hours = max(0, int(db.age_seconds(halt["set_at"], now) // 3600))
        except (TypeError, ValueError):
            hours = 0
    row = conn.execute("SELECT COUNT(*) AS n FROM machines").fetchone()
    return {"halt": halt, "halt_hours": hours,
            "halt_machines": int(row["n"] if row else 0)}


@router.get("/partials/fleet-halt-banner")
def partial_fleet_halt_banner(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """The every-page banner (UX-8, 2026-08-28). Any signed-in user: an
    editor whose sync has stopped is exactly who needs to read it."""
    if auth.get_session_user(request) is None:
        raise HTTPException(status_code=401, detail="log in first")
    return _render(request, "partials/fleet_halt_banner.html",
                   _halt_banner_context(conn))


def _fleet_halt_render(request, conn, *, error: str | None = None):
    context = _halt_banner_context(conn)
    context["error"] = error
    # UX-8: "who stopped the fleet last month and why", answered under the
    # switch that answers it.
    context["halt_history"] = db.fleet_halt_history(conn)
    return _render(request, "partials/fleet_halt.html", context)


@router.get("/partials/admin/fleet-halt")
def partial_admin_fleet_halt(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    return _fleet_halt_render(request, conn)


@router.post("/partials/admin/fleet-halt")
async def partial_admin_set_fleet_halt(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    form = await _form(request)
    active = form.get("active", "") == "1"
    reason = form.get("reason", "").strip()
    # [ KEEP HALTED ] (UX-8, 2026-08-28): the same POST, keeping the original
    # reason and start time and moving only the expiry, so the banner still
    # counts from when the fleet actually stopped.
    extend = form.get("extend", "") == "1"
    if active and not extend and len(reason) < 3:
        # The reason is shown in EVERY editor's tray. A halt with no reason
        # produces a fleet of people who cannot work and cannot find out why.
        return _fleet_halt_render(
            request, conn, error="say why -- every editor's tray will show this")
    try:
        db.set_fleet_halt(conn, active, reason, admin, extend=extend)
    except ValueError as exc:
        # UX-8 (resilience sweep 2026-08-28): a stale [ KEEP HALTED ] click,
        # submitted after the halt it meant to extend already expired, must
        # not re-halt the fleet with a blank reason -- see db.set_fleet_halt.
        return _fleet_halt_render(request, conn, error=str(exc))
    conn.commit()
    log.warning(
        "FLEET HALT %s from the Users page by %s: %s",
        "ENGAGED" if active else "released", admin, reason or "(no reason)",
    )
    return _fleet_halt_render(request, conn)


# ------------------------------------------------------------- fleet jobs
#
# TIMELINE-CARDS-INTO-CCSYNC.md phase 4 (2026-08-30). §6 names this phase's
# risk exactly: "the failure mode is invisible -- a scheduler that quietly
# assigns nothing looks exactly like a fleet with nothing to do. It needs an
# 'unschedulable, and why' view from the first commit, the way [ VRAM ] is
# shown even with nothing running." `/api/v1/jobs/<id>/why` was that view for
# anyone holding a terminal; this is it for the person who noticed a lane
# spinning, which is not the same person.


def _jobs_context(request: Request, conn, *, error: str | None = None,
                  notice: str | None = None, show_finished: bool = False) -> dict:
    from . import jobs as jobs_mod

    settings = request.app.state.settings
    caps = jobs_mod.fleet_caps(settings)
    running = db.count_running_by_kind(conn)
    executor = getattr(request.app.state, "pinned_executor", None)
    rows = []
    for job in db.list_jobs(conn, state="open", limit=100):
        # The WHY, per job, computed here rather than in the template: it is
        # five queries for the whole fleet (jobs.fleet_facts) and the template
        # must not be where a page decides how many of those to run.
        answer = jobs_mod.explain(conn, int(job["id"]), caps) or {}
        fraction = db.clamp_progress(job.get("progress"))
        rows.append({
            **job,
            "label": db.job_label(job["kind"]),
            "percent": None if fraction is None else int(round(fraction * 100)),
            "why": answer.get("summary", ""),
            "machines": answer.get("machines", []),
        })
    # WHAT THE FLEET GAVE UP ON (DDIAG-11, 2026-09-04). The count is on every
    # render because "Nothing is queued or running." over twelve abandoned
    # whisper jobs was the whole of an operator's view of them; the list
    # itself is only read when they ask for it.
    finished = []
    if show_finished:
        for job in db.finished_jobs(conn, limit=100):
            finished.append({
                **job,
                "label": db.job_label(job["kind"]),
                # A retry is offered on the two states that mean the work did
                # not happen. `done` is here to be read, not to be redone.
                "retryable": job["state"] in (db.JOB_FAILED, db.JOB_ABANDONED),
            })
    return {
        "jobs": rows,
        "finished": finished,
        "show_finished": show_finished,
        "abandoned": db.count_abandoned_jobs(conn),
        "window_hours": db.JOB_FINISHED_WINDOW_HOURS,
        "depth": db.queue_depth(conn),
        "kinds": [{"kind": kind, "label": db.job_label(kind),
                   "running": running.get(kind, 0),
                   "cap": jobs_mod.max_running(kind, caps)}
                  for kind in db.JOB_KINDS],
        "pinning": {"available": jobs_mod.can_pin(request.app),
                    "why_not": (executor.why_not() if executor is not None
                                else "no executor is configured here")},
        "error": error, "notice": notice,
    }


@router.get("/admin/jobs")
def page_admin_jobs(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "admin_jobs.html", {
        **_sidebar_context(request, conn, None),
        **_jobs_context(request, conn),
        "nav_current": "jobs",
    })


@router.get("/partials/admin/jobs")
def partial_admin_jobs(
    request: Request, finished: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
):
    # `finished` rides the poll URL the partial re-emits for itself
    # (DDIAG-11): the page refreshes every 15 s, and a toggle the next refresh
    # closes is a toggle nobody can read a list through.
    _require_admin_page(request)
    return _render(request, "partials/admin_jobs.html",
                   _jobs_context(request, conn, show_finished=bool(finished)))


@router.post("/partials/admin/jobs/{job_id}/retry")
def partial_admin_retry_job(
    job_id: int, request: Request, finished: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """[ TRY AGAIN ]. The same work, a new id, and the old row untouched.

    DDIAG-11 (2026-09-04): after the fleet spends a retry budget the operator
    had no way back but to retype the root, the relative path and the episode
    from nothing. A refusal is a sentence in the banner, never a stack
    trace on a page somebody opened because something had already gone
    wrong."""
    admin = _require_admin_page(request)
    new_id, refusal = db.retry_job(conn, job_id, created_by=admin)
    if new_id is None:
        return _render(request, "partials/admin_jobs.html",
                       _jobs_context(request, conn, show_finished=bool(finished),
                                     error=refusal or f"there is no job #{job_id}"))
    conn.commit()
    log.info("job #%s re-queued as #%s from the jobs page by %s",
             job_id, new_id, admin)
    return _render(
        request, "partials/admin_jobs.html",
        _jobs_context(request, conn, show_finished=bool(finished),
                      notice=f"job #{job_id} is on the queue again as #{new_id}. "
                             f"The old one is left as it was."))


@router.post("/partials/admin/jobs/{job_id}/cancel")
def partial_admin_cancel_job(
    job_id: int, request: Request, finished: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """[ CANCEL ]. The same three answers the API route gives, in a sentence.

    A job a MACHINE is running is not stopped here: the request rides that
    machine's next report and the companion kills its child. Saying "stopped"
    on this page while an ffmpeg is still writing into the vault would be the
    one lie this page cannot afford."""
    admin = _require_admin_page(request)
    state = db.request_job_cancel(conn, job_id, admin)
    conn.commit()
    if state is None:
        return _render(request, "partials/admin_jobs.html",
                       _jobs_context(request, conn, show_finished=bool(finished),
                                     error=f"job #{job_id} has already finished"))
    log.warning("job #%s cancelled from the jobs page by %s (%s)",
                job_id, admin, state)
    notice = (f"job #{job_id} is over"
              if state == db.JOB_FAILED else
              f"job #{job_id} will stop on its next report - the computer "
              f"running it is the only thing that can end it")
    return _render(request, "partials/admin_jobs.html",
                   _jobs_context(request, conn, show_finished=bool(finished),
                                 notice=notice))


# --------------------------------------------------------- installer download

# The drawer's [ INSTALLER ] entry points at /download. It serves the CURRENT
# kind='onboard' package
# (onboard.exe on Windows; on macOS the zipped onboarding wizard since
# installer 1.0.17, or the Terminal bootstrap script on older rows) -- the
# full clean-install/repair package, NOT the bare companion exe.
# Session-gated by app.py's login_gate like every other page: a new editor
# signs in here with the same TrueNAS credentials the wizard itself will ask
# for. Downloading to the local disk is the supported path -- running
# onboard.exe off the NAS share locks the file for everyone and is refused
# by the wizard itself.

def _detect_platform(user_agent: str) -> str:
    """'macos', 'windows', or '' when the User-Agent names neither.

    Empty is a real answer, not a failure (2026-08-18): /download used to fall
    back to Windows for anything it did not recognise, which handed a Linux
    admin -- or a browser with a trimmed UA -- an exe with no way back. It
    renders the two-platform chooser instead now, so the guess only ever fires
    when the UA actually said something.
    """
    ua = user_agent.lower()
    if "mac os" in ua or "macintosh" in ua:
        return "macos"
    if "windows" in ua:
        return "windows"
    return ""


def _installer_page(request: Request, conn: sqlite3.Connection) -> HTMLResponse:
    """The two-platform chooser. Two cheap reads, not build_packages_view: the
    whole packages view also builds the editors view, which this never shows."""
    installers = {plat: db.get_current_package(conn, plat, kind="onboard")
                  for plat in ("windows", "macos")}
    return _render(request, "installer.html", {
        **_sidebar_context(request, conn, None),
        "installers": installers,
        "detected": _detect_platform(request.headers.get("user-agent", "")),
        "nav_current": "installer",
    })


@router.get("/installer")
def page_installer(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The chooser, reachable on its own URL.

    NOT a hub page since 2026-08-18: [ INSTALLER ] in the drawer goes to
    /download, so the click is the download. This page is what /download falls
    back to for an unrecognised User-Agent, and the "other platform" link for
    the admin standing at a Windows machine setting somebody's Mac up, whom a
    UA guess can never serve. Its own URL stays because the docs and the Mac
    runbooks link it.
    """
    return _installer_page(request, conn)


@router.get("/download")
def page_download(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The [ INSTALLER ] click itself: 303 straight to this browser's package.

    The redirect is the point -- an editor told "click [ INSTALLER ]" gets a
    file, not a page about a file (2026-08-18, owner's redesign). Only a
    User-Agent that names neither platform paints anything, and what it paints
    is the chooser, so the answer to "which one do I want" is never a guess
    dressed as a download.
    """
    plat = _detect_platform(request.headers.get("user-agent", ""))
    if not plat:
        return _installer_page(request, conn)
    return RedirectResponse(f"/download/{plat}", status_code=303)


@router.get("/download/{platform}")
def page_download_platform(
    platform: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    platform = platform.strip().lower()
    if platform not in ("windows", "macos"):
        return PlainTextResponse("unknown platform -- use /download/windows or /download/macos",
                                 status_code=404)
    settings = request.app.state.settings
    row = db.get_current_package(conn, platform, kind="onboard")
    if row is None:
        # An EDITOR reads this, not the vendor's release engineer
        # (release-pipeline-11 / CR-59, 2026-08-21). It used to tell whoever
        # clicked [ INSTALLER ] to run `build_editor_package.ps1 -Publish`
        # from "the base rig" -- a repo checkout a customer's admin does not
        # have and should not need, since publish_latest.py can publish a
        # `kind=onboard` build straight from a green CI run. Two audiences,
        # two sentences: what to do now, then what an admin can do about it.
        fix = ("tools/publish_latest.py --kind onboard --platform "
               f"{platform}")
        return PlainTextResponse(
            f"No {platform} installer has been published for this fleet yet, so "
            "there is nothing to download. Ask whoever set this dashboard up "
            "for the installer.\n\n"
            f"Admins: publish one with `{fix}` (or upload it on "
            "Settings > Packages).\n",
            status_code=404,
        )
    path = settings.packages_path() / row["platform"] / row["filename"]
    if not path.is_file():
        return PlainTextResponse("installer file is missing on the server -- re-publish it",
                                 status_code=404)
    # The stored (versioned) filename is what lands in the editor's Downloads
    # folder, so "which installer did you run?" has an answer.
    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=row["filename"],
        headers={"X-CCSync-SHA256": row["sha256"], "X-CCSync-Version": row["version"]},
    )


# --------------------------------------------------------- admin packages

# "Available from the vendor" is the release feed's own section on this same
# partial (ZERO_TOUCH_PLAN.md WP E, 2026-08-17) -- one context builder shared
# by every route below that re-renders admin_packages.html, so a Check now /
# Publish / policy change never leaves the packages table and the feed
# section disagreeing about what is on this dashboard.
def _feed_next_check_seconds(last_checked_at: str | None, interval: float) -> int | None:
    """Seconds until the poller's next update check, or None when nothing can
    be said (REL-11). A check that is already overdue answers 0 rather than a
    negative: the poller sleeps in whole intervals from process start, so
    "any moment now" is the honest reading and a countdown that goes backwards
    is not."""
    if not last_checked_at:
        return None
    try:
        stamp = db.parse_iso(last_checked_at)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    elapsed = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
    return max(0, int(interval - elapsed))


def _packages_and_feed(conn, request: Request, error: str | None = None,
                       refused: list | None = None) -> dict:
    settings = request.app.state.settings
    feed = release_feed.build_feed_view(conn, settings, request.app.state)
    # REL-11 (2026-09-03): the panel said when it LAST checked and never when
    # it will check again. The default interval is a DAY, and an admin who has
    # just been told by the vendor that a fix is out reads "last checked 19
    # hours ago" and has no way to know whether waiting five minutes would
    # help. Same arithmetic the poller runs on (release_feed.FeedPoller:
    # max(POLLER_MIN_INTERVAL, settings.release_feed_interval)).
    interval = max(release_feed.POLLER_MIN_INTERVAL,
                   float(getattr(settings, "release_feed_interval", 0) or 86400.0))
    return {
        "packages": build_packages_view(conn, settings),
        "feed": feed,
        "nas_kind": getattr(settings, "nas_kind", ""),
        "feed_interval_seconds": interval,
        "feed_next_check_seconds": _feed_next_check_seconds(
            feed.get("last_checked_at"), interval),
        "error": error,
        # What the check REFUSED to take, from the check's own answer rather
        # than the stored view (2026-09-04, with the dashboard-core builder's
        # `refused` list): a build the vendor offers and this dashboard would
        # not accept is otherwise indistinguishable from one the vendor never
        # published, and both look like "nothing new".
        "feed_refused": refused or [],
    }


# ------------------------------------------- admin packages: THIS dashboard
# The dashboard's own code updates (ZERO_TOUCH_PLAN.md WP K, 2026-08-18). Its
# own partial and its own route, NOT part of _packages_and_feed: the packages
# panel is polled every 30s and an update in flight owns this one (see
# static/dashboard_update.js). Read-only server side -- every write goes
# through the JSON routes in dashboard_update.router, which are admin+CSRF
# gated like everything else that changes what runs.
@router.get("/partials/admin/dashboard-update")
def partial_admin_dashboard_update(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    error = None
    try:
        view = dashboard_update.status(settings, request.app.state)
    except Exception as exc:  # noqa: BLE001
        # Best-effort, like every optional panel on this page: a broken
        # update-status read must not take the Users page down with it.
        log.exception("could not build the dashboard-update view")
        view = {"image_mode": False, "running": dashboard_update.VERSION,
                "image": "", "source": "", "runtime_id": "", "current": {},
                "code_updates": [], "runtime_updates": [], "rollback_candidates": [],
                "nas_hint": "", "in_progress": False, "step": "idle", "message": "",
                "last_error": "", "backups": [], "boot_attempts": 0}
        error = f"could not read the code update state: {exc}"
    return _render(request, "partials/admin_dashboard_update.html",
                   {"dash_update": view, "error": error})


@router.get("/admin/packages")
def page_admin_packages(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The packages table, the vendor feed and this dashboard's own update.

    Its own page since 2026-08-18. All three panels were the bottom third of
    /admin/users, four NAS-backed panels below the fold, and the owner went
    looking for "how do I update the dashboard" and did not find it. Nothing
    moved but the address: the partials, their routes and _packages_and_feed
    are the same, so a Check now / Publish / policy change still re-renders in
    place through htmx wherever the panel is standing.
    """
    _require_admin_page(request)
    return _render(request, "admin_packages.html", {
        **_sidebar_context(request, conn, None),
        **_packages_and_feed(conn, request),
        "nav_current": "packages",
    })


@router.get("/partials/admin/packages")
def partial_admin_packages(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    return _render(request, "partials/admin_packages.html", _packages_and_feed(conn, request))


@router.post("/partials/admin/packages/current")
async def partial_admin_package_current(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    platform = form.get("platform", "").strip().lower()
    version = form.get("version", "").strip()
    kind = form.get("kind", "companion").strip().lower()
    # REL-1 (resilience sweep 2026-08-28): the same gate the JSON route is
    # held to, through the same function -- a soak gate one of the two doors
    # walks around is not a gate. `force` needs the version typed into the
    # confirmation box, which is what makes the override a decision rather
    # than a second click in the same place.
    force = form.get("force", "") == "1"
    confirm = form.get("confirm", "").strip()

    error = None
    refusal = api_make_current_refusal(
        conn, settings, kind=kind, platform=platform, version=version,
        force=force, confirm=confirm)
    if refusal is not None:
        error = refusal[1]
    elif not db.set_current_package(conn, platform, version, kind):
        error = f"no published {platform} {kind} package {version}"
    else:
        db.audit(conn, admin, "package.make_current", version,
                 {"kind": kind, "platform": platform, "version": version,
                  "forced": force})
        conn.commit()

    return _render(request, "partials/admin_packages.html", _packages_and_feed(conn, request, error))


@router.post("/partials/admin/packages/push-one")
async def partial_admin_package_push_one(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """[ PUSH TO ONE MACHINE ] -- the canary click (REL-1, 2026-08-28).

    A STAGED build is published and installable by name but offered to
    nobody; this asks one chosen machine to take that exact version on its
    next report, through the per-machine `commands.upgrade` channel that has
    existed since 2026-08-18 and already bypasses "newer only". Nothing here
    installs anything: the companion applies the signed offer it verifies for
    itself, and only when swapping the exe would not kill work in progress.
    """
    admin = _require_admin_page(request)
    form = await _form(request)
    platform = form.get("platform", "").strip().lower()
    version = form.get("version", "").strip()
    target = form.get("target", "").strip()
    editor, _sep, machine = target.partition("/")
    editor, machine = editor.strip().lower(), machine.strip()
    error = None
    if not editor or not machine:
        error = "pick a computer to push this build to"
    elif db.get_package(conn, platform, version, "companion") is None:
        error = f"no published {platform} companion package {version}"
    elif not db.request_machine_update(conn, editor, machine, version, admin,
                                       db.utcnow_iso()):
        error = f"no computer {machine!r} for {editor!r}"
    else:
        db.audit(conn, admin, "package.push_one", version,
                 {"platform": platform, "version": version,
                  "editor": editor, "machine": machine})
        conn.commit()
    return _render(request, "partials/admin_packages.html",
                   _packages_and_feed(conn, request, error))


@router.post("/partials/admin/packages/roll-fleet-back")
async def partial_admin_roll_fleet_back(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """[ ROLL THE FLEET BACK TO x ] (REL-3, 2026-08-28): every machine still
    running the recalled build is asked to take the named one instead."""
    admin = _require_admin_page(request)
    form = await _form(request)
    platform = form.get("platform", "").strip().lower()
    from_version = form.get("from_version", "").strip()
    to_version = form.get("to_version", "").strip()
    error = None
    try:
        api_roll_fleet_back_impl(conn, platform=platform, from_version=from_version,
                                 to_version=to_version, admin=admin)
    except HTTPException as exc:
        error = str(exc.detail)
    return _render(request, "partials/admin_packages.html",
                   _packages_and_feed(conn, request, error))


@router.post("/partials/admin/machines/update")
async def partial_admin_machine_update(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Ask one machine to take the current build on its next report (v25).

    The same write as POST /api/v1/admin/machines/{editor}/{machine}/update,
    from the page that already lists which machines are behind. Nothing is
    installed from here: the companion applies the signed offer it is already
    holding, and only when swapping the exe would not kill work in progress."""
    admin = _require_admin_page(request)
    form = await _form(request)
    editor = form.get("editor", "").strip().lower()
    machine = form.get("machine", "").strip()
    error = None
    row = conn.execute(
        "SELECT platform FROM machines WHERE editor_username=? AND machine=?",
        (editor, machine),
    ).fetchone()
    current = db.get_current_package(
        conn, ((row["platform"] if row else "") or "").strip().lower(), kind="companion",
    ) if row is not None else None
    if row is None:
        error = f"no computer {machine!r} for {editor!r}"
    elif current is None:
        error = "no current companion package is published for that computer's platform"
    elif not db.request_machine_update(conn, editor, machine, current["version"],
                                       admin or "admin", db.utcnow_iso()):
        error = f"no computer {machine!r} for {editor!r}"
    else:
        conn.commit()
    return _render(request, "partials/admin_packages.html",
                   _packages_and_feed(conn, request, error))


@router.post("/partials/admin/machines/resume-lane-b")
async def partial_admin_resume_lane_b(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Clear one machine's lane B breaker on its next report (v26, CR-45).

    The same write as POST
    /api/v1/admin/machines/{editor}/{machine}/resume-lane-b, from the fleet
    page that is already showing the red chip. Re-renders the fleet grid so
    the admin sees the request land."""
    admin = _require_admin_page(request)
    form = await _form(request)
    editor = form.get("editor", "").strip().lower()
    machine = form.get("machine", "").strip()
    # UX-20 (resilience sweep 2026-08-28): the return value used to be thrown
    # away, so RESUME on a fleet page left open across a rename or a
    # [ FORGET ] re-rendered looking fine and queued nothing -- and the
    # editor's proxies stayed stopped until somebody noticed.
    resumed = db.request_lane_b_resume(conn, editor, machine, admin, db.utcnow_iso())
    conn.commit()
    scope = auth.scope_for(request)
    return _render(request, "partials/fleet_grid.html", {
        "view": api_scope_projects_view(build_projects_view(conn), scope),
        "fleet": api_scope_editors_view(build_editors_view(conn), scope),
        "error": None if resumed else (
            "That computer is no longer in the fleet, so nothing was resumed. "
            "Reload the page."),
    })


@router.post("/partials/admin/machines/ask-why")
async def partial_admin_ask_why(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """[ ASK THIS MACHINE WHY ] (v33, SYS-7, resilience sweep 2026-08-28).

    Writes the one-shot request the next report reply carries, exactly as the
    RESUME button beside it does. The admin who has just read "Not syncing:
    the sync drive is not there on this computer" wants the whole bundle, and
    until now the only route to it was asking a non-technical editor to click
    Copy diagnostics on the machine that was broken.

    Re-renders the fleet grid so the ASKED chip appears immediately; a refusal
    (an unknown machine) shows as the row simply staying put, the same way the
    two buttons beside it behave."""
    admin = _require_admin_page(request)
    form = await _form(request)
    editor = form.get("editor", "").strip().lower()
    machine = form.get("machine", "").strip()
    if not db.request_diagnostics(conn, editor, machine, admin, db.utcnow_iso()):
        log.warning("ask-why refused: no machine %r for %r", machine, editor)
    conn.commit()
    scope = auth.scope_for(request)
    return _render(request, "partials/fleet_grid.html", {
        "view": api_scope_projects_view(build_projects_view(conn), scope),
        "fleet": api_scope_editors_view(build_editors_view(conn), scope),
    })


@router.get("/partials/admin/diagnostics")
def partial_admin_diagnostics(
    request: Request, editor: str = "", machine: str = "",
    conn: sqlite3.Connection = Depends(get_conn)
):
    """The stored diagnostics bundles (v33, SYS-7).

    ADMIN ONLY, and not merely by convention: a bundle names an editor's
    paths, their Resolve project and their tree, which is exactly what
    COMMERCIAL_READINESS.md §C L1 says one editor may not read about another.

    Lives OUTSIDE the fleet-grid wrapper on the page, so the grid's own 15 s
    poll cannot swap an open bundle out from under whoever is reading it.
    """
    _require_admin_page(request)
    editor = editor.strip().lower()
    machine = machine.strip()
    if editor or machine:
        bundles = db.fetch_diagnostics(conn, editor=editor or None,
                                       machine=machine or None, limit=5)
    else:
        bundles = db.newest_diagnostics_per_machine(conn)
    return _render(request, "partials/admin_diagnostics.html", {
        "diagnostics": {"bundles": bundles, "editor": editor, "machine": machine},
        "crash_reports": len(notices.crash_files(request.app.state.settings)),
        # DCORE-16: the same list as the project page's. A machine that is
        # not getting its shares because an enforce cycle has been half
        # failing for a week is a fleet-level answer, and this panel is where
        # an admin looks for one.
        "enforce_notes": db.enforce_notes(conn),
    })


@router.get("/admin/diagnostics/crash-reports.zip")
def admin_crash_reports_zip(request: Request):
    """[ DOWNLOAD CRASH REPORTS ] (DDIAG-10, usability sweep 2026-09-03).

    crash_report.py has written <data>/crashes/*.json since 2026-08-17 and
    nothing ever read that directory: the collector thread dying was a fact
    only somebody with a shell in the container could get at, and that person
    is the one this whole sweep assumes does not exist.

    ADMIN ONLY, like the diagnostics bundles beside it: a traceback names this
    server's paths. The zip is built in memory (notices.crash_zip_bytes) and
    nothing is written into the data volume to serve it."""
    _require_admin_page(request)
    payload, count = notices.crash_zip_bytes(request.app.state.settings)
    return Response(
        content=payload, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="ccsync-crash-reports.zip"',
                 "X-CCSync-Crash-Files": str(count)})


@router.post("/partials/admin/machines/forget-lost")
async def partial_admin_forget_lost_machine(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """Forget one LOST computer from the fleet page (DASH-16, resilience sweep
    2026-08-28).

    Same implementation as the Users page's [ REMOVE ] and the JSON twin, and
    deliberately a second route rather than a shared one: this one re-renders
    the FLEET GRID, and the admin who is looking at a LOST row is looking at
    it there. A refusal shows as the row simply staying put, exactly as it
    does for the RESUME button beside it."""
    admin = _require_admin_page(request)
    form = await _form(request)
    editor = form.get("editor", "").strip().lower()
    machine = form.get("machine", "").strip()
    try:
        forget_machine_everywhere(request, conn, editor, machine, admin=admin)
    except HTTPException as exc:
        log.warning("forget of lost machine %s/%s refused: %s", editor, machine,
                    exc.detail)
    scope = auth.scope_for(request)
    return _render(request, "partials/fleet_grid.html", {
        "view": api_scope_projects_view(build_projects_view(conn), scope),
        "fleet": api_scope_editors_view(build_editors_view(conn), scope),
    })


@router.post("/partials/admin/machines/update/cancel")
async def partial_admin_machine_update_cancel(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    form = await _form(request)
    db.clear_machine_update_request(
        conn, form.get("editor", "").strip().lower(), form.get("machine", "").strip())
    conn.commit()
    return _render(request, "partials/admin_packages.html",
                   _packages_and_feed(conn, request, None))


# How long a deleted package's bytes stay recoverable (UX-9, 2026-08-28).
# A rollback that has to reach for one is a bad day already; 30 days is long
# enough to be there and short enough that the volume the whole dashboard
# writes to does not fill with builds nobody wants.
# UX-9 (resilience sweep 2026-08-28): the trash helpers live in api.py so the
# JSON DELETE route and this partial share ONE delete mechanism.
from .api import PACKAGE_TRASH_DAYS, _prune_package_trash, _trash_package_file  # noqa: E402


@router.post("/partials/admin/packages/delete")
async def partial_admin_package_delete(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    admin = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    platform = form.get("platform", "").strip().lower()
    version = form.get("version", "").strip()
    kind = form.get("kind", "companion").strip().lower()

    error = None
    row = db.get_package(conn, platform, version, kind)
    if row is None:
        error = f"no published {platform} {kind} package {version}"
    elif row["is_current"]:
        error = "cannot delete the current version; make another version current first"
    else:
        # UX-9 (resilience sweep 2026-08-28): these are the bytes a rollback
        # needs. They go to <data>/packages/.trash/ for 30 days instead of
        # being unlinked, and a failure to move them is SAID rather than
        # swallowed -- the old code passed on OSError, so a read-only or full
        # volume dropped the row and kept the file, which is the one
        # combination that makes the package permanently unrecoverable AND
        # invisible.
        moved, move_error = _trash_package_file(settings, row)
        if move_error is not None:
            error = move_error
        else:
            db.delete_companion_package(conn, platform, version, kind)
            db.audit(conn, admin, "package.delete", version,
                     {"kind": kind, "platform": platform, "version": version,
                      "trashed": moved})
            conn.commit()

    return _render(request, "partials/admin_packages.html", _packages_and_feed(conn, request, error))


# ------------------------------------------------------------- setup wizard
# ZERO_TOUCH_PLAN.md WP D / §3.5, 2026-08-17. The page is a thin shell --
# every task's Check/Do it/Skip and the studio form post straight to
# setup_routes.py's API (static/setup.js) -- so this route's only job is
# deciding WHO may see it at all.

@router.get("/setup")
def page_setup(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is not None and not auth.is_admin(settings, user):
        # "do not trap non-admins" (the work package) -- an editor who
        # follows a stale /setup link (or types it) goes to their own grid,
        # not a page every control on which will 403 for them anyway.
        return RedirectResponse("/", status_code=303)
    if user is None:
        from . import setup_routes

        if not setup_routes.first_run_open(request, conn):
            return RedirectResponse(f"/login?next={quote('/setup', safe='')}", status_code=303)
    return _render(request, "setup.html", {"nav_current": "setup"})


# --------------------------------------------------------------- settings

def _live_auto_derived_values(settings) -> dict[str, str]:
    """Which of site_store.AUTO_DERIVED_KEYS has a LIVE value available RIGHT
    NOW, and a short human sentence saying where it came from -- what the
    Settings page greys a field out FOR (CR-follow-up, 2026-08-30, the owner:
    "it won't let me change the dashboard url").

    Before this, `admin_settings.html` greyed a key out whenever it was IN
    AUTO_DERIVED_KEYS **and the DB row had ever been given any value at
    all** -- which every one of them had, from the very first boot's env
    seed (`site_store.seed_from_env_once`), so the three fields locked
    FOREVER the moment a deployment had any DASH_SITE_* set once. Nothing
    about that meant a live source was actually deriving anything: Alex's
    dashboard_url was a value someone typed (or the env seeded) months ago,
    not a value WP B's Tailscale sidecar was deriving today, and the docs
    already promised the opposite (docs/CONFIG.md: "greys those out only
    when a live value is actually available").

    Each check is bounded and fails to "no live value" on anything short of
    a real, current answer -- a page an admin is looking at must not hang
    behind a NAS that stopped answering:

      - dashboard_url: the bundled Tailscale sidecar (tailscale_local.py, WP
        B), signed in with a resolvable name. `socket_present()` is a
        Path.exists() on a unix socket -- no network at all -- so a
        deployment with no WP B sidecar container (every one today,
        including Alex's, which reaches its dashboard through a tailnet URL
        he set by hand) answers instantly and never greys the field.
      - nas_syncthing_id: this site's own Syncthing, `/rest/system/status`'s
        `myID` -- the exact call `setup_engine._check_syncthing` already
        makes for the same reason, bounded to 2 s here too.
      - sftp_host: WP C's SFTP sidecar has no OUTBOUND status route in this
        repo yet -- `internal_sftp.py` is inbound identity only, called BY
        the sidecar, never calling it. No live source exists, so this key is
        never in the answer, full stop, until that changes.
    """
    live: dict[str, str] = {}

    from . import tailscale_local
    try:
        node = tailscale_local.summarise(tailscale_local.status())
    except Exception:                                                # noqa: BLE001
        node = None
    if node and node.get("backend_state") == "Running":
        name = node.get("dns_name") or ((node.get("ips") or [None])[0])
        if name:
            live["dashboard_url"] = f"the bundled Tailscale sidecar is signed in as {name}"

    syncthing_url = str(getattr(settings, "syncthing_url", "") or "")
    if syncthing_url:
        try:
            client = SyncthingClient.from_settings(settings)
            client.timeout = min(client.timeout, 2.0)
            my_id = str(client.system_status().get("myID", "") or "")
        except Exception:                                             # noqa: BLE001
            my_id = ""
        if my_id:
            live["nas_syncthing_id"] = f"this site's Syncthing reports device id {my_id[:7]}..."

    return live


def _auto_derived_env_hints(settings, manifest: dict) -> dict[str, str]:
    """DASH_SITE_* for each AUTO_DERIVED_KEY, shown as a fallback hint
    whenever it DIFFERS from the DB row (2026-08-30 follow-up).

    Found the same night: the container's env carried
    `DASH_SITE_DASHBOARD_URL=https://truenas.tail26290e.ts.net:9443` while
    the DB row (what the field showed, and -- before this fix -- could not
    be changed) held `http://100.71.216.3:8480`. `site_store`'s own rule is
    that the DB is authoritative once written and the env is never picked up
    automatically (docs/CONFIG.md) -- right for avoiding a surprise value
    change on a restart, wrong for leaving the admin unable to even SEE that
    the two disagree. This never auto-fills anything; it is text beside the
    field.
    """
    from . import site_store

    hints: dict[str, str] = {}
    for key in site_store.AUTO_DERIVED_KEYS:
        env_val = str(getattr(settings, f"site_{key}", "") or "").strip()
        db_val = str(manifest.get(key) or "").strip()
        if env_val and env_val != db_val:
            hints[key] = env_val
    return hints


@router.get("/admin/settings")
def page_admin_settings(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    from . import site_store

    settings = request.app.state.settings
    manifest = site_store.resolved_manifest(conn, settings)
    live_derived = _live_auto_derived_values(settings)
    return _render(request, "admin_settings.html", {
        **_sidebar_context(request, conn, None),
        "manifest": manifest,
        # ONLY the keys with a LIVE value available right now (see
        # _live_auto_derived_values) -- never the full AUTO_DERIVED_KEYS set,
        # which is "could be derived once a sidecar exists", not "is".
        "auto_derived": sorted(live_derived.keys()),
        "auto_derived_reason": live_derived,
        "env_hint": _auto_derived_env_hints(settings, manifest),
        "from_db": set(manifest.get("_from_db", ())),
        # A CHOICE, not free text (dash-admin-7, 2026-08-21): the field used
        # to be a plain input, so "TrueNAS" or a trailing space reached every
        # installer through the manifest while nas.factory kept using
        # DASH_NAS_KIND. site_store.validate refuses anything not in this
        # list; offering exactly the list is how an admin never meets that
        # refusal.
        "nas_kinds": list(nas_factory.NAS_KINDS),
        "nav_current": "site",
    })


# ------------------------------------------------- admin packages: release feed
# HTML twins of the JSON routes in release_feed.router (/api/v1/admin/feed*):
# same underlying functions, so "Check now"/"Publish"/policy behave IDENTICALLY
# whether driven from this page or from a script -- these routes are only the
# htmx glue (admin auth, form parsing, re-rendering the partial), matching
# every other route on this page. See release_feed.py for the actual logic.

@router.post("/partials/admin/feed/check")
def partial_admin_feed_check(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    _require_admin_page(request)
    settings = request.app.state.settings
    error = None
    refused: list = []
    if not settings.release_feed_url:
        error = "DASH_RELEASE_FEED_URL is not configured"
    else:
        result = release_feed.check_now(conn, settings, request.app.state)
        if not result["ok"]:
            error = f"feed check failed: {result.get('error')}"
        # Tolerant of a release_feed that predates the key: a check that
        # cannot say what it refused must not be the reason this page 500s.
        refused = list(result.get("refused") or [])

    return _render(request, "partials/admin_packages.html",
                   _packages_and_feed(conn, request, error, refused))


@router.post("/partials/admin/feed/publish")
async def partial_admin_feed_publish(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    user = _require_admin_page(request)
    settings = request.app.state.settings
    form = await _form(request)
    kind = form.get("kind", "companion").strip().lower()
    platform = form.get("platform", "").strip().lower()
    version = form.get("version", "").strip()
    make_current = form.get("make_current", "") == "1"

    error = None
    if not settings.release_feed_url:
        error = "DASH_RELEASE_FEED_URL is not configured"
    else:
        try:
            # REL-2 (2026-09-04): this downloads the artefact from the vendor
            # feed with a 600 s timeout (release_feed.ARTIFACT_FETCH_TIMEOUT),
            # synchronously. The route is `async` only because it awaits the
            # form, so that download used to run ON the event loop -- and
            # deploy/run.sh runs uvicorn with --workers 1, so one admin's
            # [ PUBLISH ] stalled every companion report, every lane status,
            # the fleet grid and all four mounts for as long as it took. The
            # JSON twin (release_feed.py's plain `def` route) was always
            # correct; this is the button a human actually clicks.
            await run_in_threadpool(
                release_feed.publish_from_feed,
                conn, settings, request.app.state, kind=kind, platform=platform,
                version=version, make_current=make_current, published_by=user,
            )
        except package_store.PackageStoreError as exc:
            error = exc.detail

    return _render(request, "partials/admin_packages.html", _packages_and_feed(conn, request, error))


@router.post("/partials/admin/feed/policy")
async def partial_admin_feed_policy(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    _require_admin_page(request)
    form = await _form(request)
    error = None
    try:
        release_feed.set_policy(conn, form.get("policy", ""))
    except ValueError as exc:
        error = str(exc)

    return _render(request, "partials/admin_packages.html", _packages_and_feed(conn, request, error))


# -- the installable app: manifest, service worker, offline page ------------
# MOBILE_PLAN.md 4 M4, 2026-08-30. All three are in app._OPEN_EXACT, and they
# have to be: a browser fetches the manifest and registers the worker on the
# LOGIN page, before anyone has a session, and the offline page is precached
# by that worker at install time. Which is also the rule for what may live in
# them -- a product name, a colour and five icons. Never a count, never a name
# from this fleet, never anything a second tenant should not read.


@router.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest(request: Request) -> Response:
    """The web app manifest, with this site's product name in it.

    static/manifest.webmanifest is the source AND the fallback, which is why
    the brand is substituted here rather than the file being a Jinja template:
    a `{{ }}` in it would stop it being valid JSON, and then a site whose
    manifest could not be read would hand the phone a broken install instead
    of the vendor's default one.
    """
    path = STATIC_DIR / "manifest.webmanifest"
    settings = request.app.state.settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # The same value _render puts in the topbar (brand_product), from the
        # RESOLVED site manifest -- so an install's icon label matches the
        # header the editor signed in under.
        site = site_store.manifest_for_app(request.app, settings)
        brand = (site.get("product_name") or settings.site_product_name or "").strip()
        if brand:
            data["name"] = brand
            data["short_name"] = brand
        body = json.dumps(data, indent=2)
    except Exception:  # noqa: BLE001
        log.exception("could not render the web app manifest; serving the file")
        if not path.is_file():
            return PlainTextResponse("no manifest on this server", status_code=404)
        return FileResponse(str(path), media_type="application/manifest+json")
    return Response(content=body, media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    """The service worker, at the ROOT so it may claim scope "/".

    A worker's scope can never be above its own path, so /static/sw.js could
    only ever control /static/ -- hence this route plus Service-Worker-Allowed.
    Cache-Control: no-cache so the browser revalidates the worker itself on
    every update check; the VERSION substitution is what makes an update
    visible (a byte-identical worker is never installed).
    """
    path = STATIC_DIR / "sw.js"
    if not path.is_file():
        return PlainTextResponse("no service worker on this server", status_code=404)
    body = path.read_text(encoding="utf-8").replace("__VERSION__", VERSION)
    return Response(
        content=body,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@router.get("/offline")
def page_offline(request: Request):
    """What the worker paints when a navigation cannot reach the server.

    Rendered as if NOBODY were signed in (bug-hunt-2026-09-03
    dash-mounts-ui-2). sw.js precaches this page with the session cookie
    attached and keeps the copy until VERSION changes the cache name, so a
    normal _render froze one specific editor's name, their "(admin)" drawer
    and a live CSRF token into a page any later user of that browser sees.
    _render's context is setdefault, so seeding the three session keys here
    is the whole fix.
    """
    return _render(request, "offline.html",
                   {"session_user": None, "session_is_admin": False, "csrf_token": ""})


@router.get("/help")
def page_help(request: Request):
    """The customer guide, rendered (UX-3 / SYS-21a).

    Behind the login gate (app.py) and brand-substituted like every other
    page. help.py owns finding the document and turning it into HTML; a
    server with no copy of it gets one sentence, never a 500.
    """
    context = help_page.page_context()
    context["nav_current"] = "help"
    return _render(request, "help.html", context)
