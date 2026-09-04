"""The Settings window -- everything the reduced tray menu no longer shows
(2026-08-27, the tray-menu-reduction pass; see tray.py's module docstring
and _build_menu's for what stayed).

Split into two layers on purpose, the same split popup.py's dialogs don't
need but this one does because it has to be UNIT TESTABLE without a display:

    build_settings_model(snap, app) -> list[Section]
        Pure. Turns a tray snapshot (tray._tray_snapshot's dict) into a list
        of Section objects -- headers, disabled Lines, and Buttons whose
        `on_click` is a bound, zero-arg callable. No tkinter import, no I/O
        beyond what `snap`/`app` already carry. Tests exercise this directly.

    show_settings(app) -> None
        Renders that model as a scrollable Tk window in the same "signature
        red CLI style" every dialog in this package uses (theme.py), and
        refreshes it from a fresh snapshot every ~2s. This half is what
        actually opens tkinter and is expected to be exercised only by a
        human or an end-to-end test with a real display.

Every button follows ONE rule, uniformly, because two Tk roots alive at once
is the sibling-Tk-root hazard AUDIT_2 CORE-M3/H8 describes (see
copy_diagnostics's docstring in app.py): a click closes THIS window,
releases its hold on `_popup_active_lock`, and only THEN spawns the actual
action on a worker thread via tray._spawn -- exactly the pattern
_confirm_remove_project already uses for a dialog opened from the tray menu.
This is deliberately uniform rather than case-by-case (a "Sync now" click
does not strictly need to close the window) because it is the one rule that
can never be wrong: every action here either opens no window at all (safe
either way) or opens one of the themed dialogs (unsafe with this window still
up), and treating all of them the same way is simpler than auditing each one
every time a new button is added here.
"""

from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from . import config as config_mod
from . import site as site_mod
from . import tray as tray_mod
from . import ui_copy
from . import upgrade as upgrade_mod
from . import ytdl_cookies

if TYPE_CHECKING:
    from .app import CompanionApp

log = logging.getLogger("ccsync.settings")


@dataclass
class Line:
    """A disabled, informational row. `style` picks the colour in the Tk
    renderer: "normal" (TEXT), "muted" (MUTED), "warning" (RED)."""

    text: str
    style: str = "normal"


@dataclass
class Button:
    """A clickable row. `on_click` is already bound to `app` (and to
    whatever snapshot-derived arguments it needs) -- callers never pass
    `app` again at click time."""

    label: str
    on_click: Callable[[], None]


@dataclass
class Section:
    title: str
    items: list  # list[Line | Button]


# -- SYNC-118: an advisory has a RANK ---------------------------------------
#
# Every `_*_line` producer used to be appended with style="warning", in source
# order, so a machine having a bad week showed a dozen equally loud red lines
# with the one sentence that matters at the bottom, next to "Recoverable files
# in .ccsync-trash: 12 GB", which is not a problem at all. The severity here is
# a property of the PRODUCER, not of the text: only the producer knows whether
# its sentence means "nothing is syncing" or "here is a number".
BLOCKING = "blocking"
WARNING = "warning"
INFO = "info"
_SEVERITY_ORDER = (BLOCKING, WARNING, INFO)
# The three colours the renderer has. Red is reserved for the tier that means
# work is not reaching the server.
_SEVERITY_STYLE = {BLOCKING: "warning", WARNING: "normal", INFO: "muted"}
# How many advisories are drawn before the rest go behind [ SHOW ALL ].
_ADVISORY_CAP = 6

# Toggled by [ SHOW ALL ] / [ SHOW FEWER ]. Module level rather than an
# attribute of the window because build_settings_model is pure and the window
# rebuilds it from a fresh snapshot every two seconds -- a flag on the widget
# tree would be forgotten twice a second.
_show_all_advisories = {"on": False}


def advisories_shown_in_full() -> bool:
    return bool(_show_all_advisories["on"])


def action_show_all_advisories(app: "CompanionApp", show: bool) -> None:
    """[ SHOW ALL ] / [ SHOW FEWER ] (SYNC-118).

    Reopens the window: every button here closes it first (see the module
    docstring's one rule), and a toggle that left the editor looking at a
    closed window would be a button that appears to do nothing."""
    _show_all_advisories["on"] = bool(show)
    show_settings(app)


def collapse_advisories(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Identical sentences become one with a count (SYNC-118).

    Two producers can legitimately say the same thing (the blocked summary
    repeats a lane line often enough that _BLOCKED_REASONS_WITH_THEIR_OWN_LINE
    exists), and the same sentence twice reads as two problems. The highest
    severity wins: a sentence that blocks sync does not become advisory
    because something quieter said it too."""
    order: list[str] = []
    seen: dict[str, list] = {}
    for severity, text in entries:
        if not text:
            continue
        if text not in seen:
            order.append(text)
            seen[text] = [severity, 0]
        seen[text][1] += 1
        if _SEVERITY_ORDER.index(severity) < _SEVERITY_ORDER.index(seen[text][0]):
            seen[text][0] = severity
    out: list[tuple[str, str]] = []
    for text in order:
        severity, count = seen[text]
        out.append((severity, text if count < 2 else f"{text} (x{count})"))
    return out


def rank_advisories(entries: list[tuple[str, str]], show_all: bool = False):
    """(lines, hidden) -- ranked, collapsed and capped (SYNC-118).

    Stable within a tier: the source order of the producers is itself an
    ordering somebody chose (the blocked summary is deliberately last), and
    re-sorting inside a tier would lose it."""
    collapsed = collapse_advisories(entries)
    ranked = [e for severity in _SEVERITY_ORDER for e in collapsed if e[0] == severity]
    hidden = 0
    if not show_all and len(ranked) > _ADVISORY_CAP:
        hidden = len(ranked) - _ADVISORY_CAP
        ranked = ranked[:_ADVISORY_CAP]
    return ([Line(text, style=_SEVERITY_STYLE.get(severity, "normal"))
             for severity, text in ranked], hidden)


def _lane_advisories(guard: dict, skip_blocked: bool = False) -> list[tuple[str, str]]:
    """Every `_*_line` producer, tagged (SYNC-118).

    BLOCKING is the strict test "nothing, or one whole lane, is reaching the
    server while this is true". A rejected credential is blocking because the
    machine is dark on the fleet grid; a clock skew is, because lane B
    transfers nothing; recoverable trash never is.

    `skip_blocked` drops the blocked SUMMARY when the caller has already
    rendered that same sentence with a button under it (APP-9's licence
    line) -- the same reason _BLOCKED_REASONS_WITH_THEIR_OWN_LINE exists."""
    producers = (
        (BLOCKING, tray_mod._halt_line),
        (BLOCKING, tray_mod._breaker_line),
        (WARNING, tray_mod._skipped_exists_line),
        (BLOCKING, tray_mod._unfiltered_line),
        (WARNING, tray_mod._conflicts_line),
        (BLOCKING, tray_mod._reporter_line),
        (BLOCKING, tray_mod._clock_skew_line),
        (INFO, tray_mod._ignored_line),
        (WARNING, tray_mod._crashes_line),
        (WARNING, tray_mod._restarts_line),
        (WARNING, tray_mod._upgrade_line),
        (WARNING, tray_mod._reverted_line),
        (BLOCKING, tray_mod._stalled_line),
        (BLOCKING, tray_mod._disk_line),
        (BLOCKING, tray_mod._blocked_line),
        (INFO, tray_mod._trash_line),
    )
    out: list[tuple[str, str]] = []
    for severity, producer in producers:
        if skip_blocked and producer is tray_mod._blocked_line:
            continue
        try:
            text = producer(guard)
        except Exception:
            # One broken producer must not cost the editor the other fifteen.
            log.exception("settings: the %s advisory failed", getattr(
                producer, "__name__", producer))
            continue
        if text:
            out.append((severity, text))
    return out


def _licence_advisory(guard: dict) -> str:
    """The licence-refused sentence with the wizard instruction removed
    (APP-9, sweep 2026-09-03).

    eula.acceptance_problem() ends all three of its sentences with "Re-run the
    CCSync setup wizard to read and accept it" -- the largest action available
    -- while this window can accept it in one click. The log keeps the
    original wording; the editor is given the button instead."""
    blocked = (guard or {}).get("blocked") or {}
    if not isinstance(blocked, dict) or blocked.get("reason") != "licence_pending":
        return ""
    detail = str(blocked.get("detail") or "").strip()
    if not detail:
        return ""
    kept = [s for s in detail.split(". ") if "setup wizard" not in s.lower()]
    sentence = ". ".join(p.strip().rstrip(".") for p in kept if p.strip())
    return f"⚠ {sentence}. Nothing syncs until it is accepted." if sentence else ""


def action_accept_licence(app: "CompanionApp") -> None:
    """[ READ AND ACCEPT THE LICENCE ] (APP-9). app.open_licence_dialog is
    the newer entry point; the tray action is what shipped before it."""
    opener = getattr(app, "open_licence_dialog", None)
    if callable(opener):
        tray_mod._spawn(app, "Accept the licence agreement", opener)
        return
    tray_mod.action_accept_licence(app)


def _credential_refused(guard: dict) -> bool:
    """The dashboard is rejecting this computer's sign-in (APP-8).

    identity.valid() is a purely LOCAL check, so a token the server has
    revoked still reads as signed in and the window offered [ SIGN OUT ] and
    nothing else. The reporter's own last status is the only thing on this
    machine that knows better."""
    health = (guard or {}).get("reporter") or {}
    if not isinstance(health, dict):
        return False
    try:
        streak = int(health.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        return False
    if streak < tray_mod.REPORTER_FAILURE_STREAK:
        return False
    return str(health.get("last_status") or "") in ("HTTP 401", "HTTP 403")


def action_sign_in_again(app: "CompanionApp") -> None:
    """[ SIGN IN AGAIN ] (APP-8). app.sign_in_again() when the app carries it,
    otherwise the sign-in dialog, which already overwrites the identity."""
    again = getattr(app, "sign_in_again", None)
    if callable(again):
        tray_mod._spawn(app, "Sign in again", again)
        return
    tray_mod.action_sign_in(app)


def action_restart(app: "CompanionApp") -> None:
    """[ RESTART CCSYNC NOW ] (APP-13). The tray's own restart action when it
    exists, so the menu and this window are the same code path."""
    restart = getattr(tray_mod, "action_restart", None)
    if callable(restart):
        restart(app)
        return
    action_restart_now(app)


def _ignored_folders(app: "CompanionApp") -> list[dict]:
    """The persisted "always leave this folder alone" entries (RES-12).

    Read through the app rather than the file so the window shows what the
    running tracker is actually honouring. Never raises: an unreadable
    ignore list must cost the [ FORGET ] buttons, not the whole window."""
    try:
        return list(app.ignore_tracker.folders())
    except Exception:
        log.exception("settings: could not read the leave-alone folder list")
        return []


def _role_label(role: str) -> str:
    return "WIRED TO THE SERVER" if role == "base" else "REMOTE EDITOR"


def _mode_needs_restart(app: "CompanionApp") -> bool:
    """True once config.toml's `mode` on disk differs from the value THIS
    process started with -- the role switch writes the file but never
    mutates the live config (a live mutation would change `mode` while
    leaving every OTHER MODE_PROFILES-derived default, like
    lane_b_enabled, stale -- see config.py's MODE_PROFILES and
    app.py's __init__). A restart re-runs load_config() and picks up
    everything at once."""
    try:
        on_disk = config_mod.load_config(config_mod.CONFIG_PATH).get("mode", "editor")
        current = app.config.get("mode", "editor")
        return str(on_disk).strip().lower() != str(current).strip().lower()
    except Exception:
        log.exception("settings: could not check whether mode needs a restart")
        return False


def action_set_role(app: "CompanionApp", role: str) -> None:
    """Write config.toml's `mode` -- the COMPUTER's role since 2026-08-27
    (see app.effective_mode()'s docstring, MULTI_BASE_RIG_PLAN.md WP0/WP1).

    Switching TO "editor" (REMOTE EDITOR) is the dangerous direction on a
    machine whose local_root really is the live NAS share (the actual base
    rig): lane B would start a deleting `rclone sync` DOWNWARD onto it the
    moment a pass ran (AUDIT_2 CORE-C1) -- the one direction here that can
    destroy footage stored nowhere else. It is gated behind the same
    typed-word confirmation the project-removal gate uses (expected word
    "REMOTE"), which is why this function -- unlike every other Settings
    action -- takes the popup lock itself: it is called from a worker
    thread AFTER the Settings window has already closed and released its
    own hold on the lock (see the module docstring's "one rule").

    Switching TO "base" (WIRED TO THE SERVER) destroys nothing, but it is
    the one click in the companion that turns ALL syncing off for good on a
    machine that needs it, and it used to have no dialog at all (UX-2,
    resilience sweep 2026-08-28): an editor who clicked it out of curiosity
    because their desk is in the office got a toast saying the role changed
    and, from the next start, three dead lanes and a dashboard that could
    not tick a project for them. Plain yes/no rather than the typed-word
    gate: the consequence is "nothing syncs", not "footage is deleted".
    """
    role = "base" if str(role).strip().lower() == "base" else "editor"
    if role == "base":
        from . import popup

        lock = getattr(app, "_popup_active_lock", None)
        if lock is not None and not lock.acquire(blocking=False):
            tray_mod._notify(app, "Another CCSync window is already open. Close it first.")
            return
        try:
            body = (
                "Set this computer to WIRED TO THE SERVER? A wired computer "
                "works straight off the server share, so CCSync will sync "
                "NOTHING to it: no upload, no proxy download, no folder "
                "sync. Your admin will not be able to tick projects "
                "for it either. If this laptop keeps its own copy of the "
                "projects, this is not the setting you want."
            )
            confirmed = popup.confirm_dialog(
                site_mod.notify_title("switch to WIRED TO THE SERVER"), body,
                ok_label="WIRED TO THE SERVER",
            )
        finally:
            if lock is not None:
                lock.release()
        if not confirmed:
            return
    if role == "editor":
        lock = getattr(app, "_popup_active_lock", None)
        if lock is not None and not lock.acquire(blocking=False):
            tray_mod._notify(app, "Another CCSync window is already open. Close it first.")
            return
        try:
            body = (
                "Switch this computer to REMOTE EDITOR?\n\n"
                "A REMOTE EDITOR computer syncs projects DOWN to its own "
                "drive. If this computer's synced folder is actually the "
                "live server share, switching will start "
                "DELETING files from it the moment a proxy download runs, "
                "because proxy download syncs the server DOWN onto "
                "whatever this computer calls its own copy.\n\n"
                "If you are not sure this computer has its own separate "
                "copy of the project tree, do not do this.\n\n"
                'Type "REMOTE" to confirm:'
            )
            confirmed = tray_mod._ask_typed_confirmation_locked(
                app, site_mod.notify_title("switch to REMOTE EDITOR"), body, "REMOTE",
            )
        finally:
            if lock is not None:
                lock.release()
        if not confirmed:
            return
    try:
        # False, not an exception, when the line was written but load_config
        # cannot read it back (APP-11, 2026-08-28) -- the shape that made this
        # button silently do nothing forever on a config.toml with a
        # hand-added [table].
        saved = config_mod.set_value(config_mod.CONFIG_PATH, "mode", role)
    except Exception:
        log.exception("settings: could not write mode=%s to config.toml", role)
        tray_mod._notify(app, "Couldn't save that -- see the log.")
        return
    if not saved:
        tray_mod._notify(app, "Couldn't save that -- see the log.")
        return
    tray_mod._notify(
        app, f"This computer is now set to {_role_label(role)}. Takes effect "
             "the next time CCSync starts -- open Settings to restart now.")


def action_restart_now(app: "CompanionApp") -> None:
    """The same relaunch apply_upgrade uses after an install
    (upgrade.restart_self), without the download/swap -- the general
    "reload config.toml by starting over" path this app already has."""
    def _do() -> None:
        blocker = getattr(app, "_standing_down_would_kill_work", lambda: "")()
        if blocker:
            tray_mod._notify(
                app, "Can't restart while a CCSync window is open or media is "
                     "being copied in. Try again once it's done.")
            return
        try:
            upgrade_mod.restart_self(request_shutdown=app.shutdown)
        except Exception:
            log.exception("settings: restart_self failed")
    tray_mod._spawn(app, "Restart CCSync", _do)


def action_repair_p_mapping(app: "CompanionApp") -> None:
    """[ REPAIR P: NOW ] (UX-15, resilience sweep 2026-08-28).

    The broken-mapping toast has always described this repair and never
    offered it. app.repair_p_mapping keeps UX-6's ownership check, so a P:
    somebody else created is refused with what it points at, not replaced.
    """
    def _do() -> None:
        try:
            ok, message = app.repair_p_mapping()
        except Exception:
            log.exception("settings: repair of the media drive mapping failed")
            tray_mod._notify(app, "CCSync could not repair the drive mapping. "
                                  f"{ui_copy.DIAGNOSTICS}.")
            return
        tray_mod._notify(app, message)
        if ok:
            log.info("settings: media drive mapping repaired")
    tray_mod._spawn(app, "Repair drive mapping", _do)


def action_forget_ignored_folder(app: "CompanionApp", folder: str) -> None:
    """[ FORGET ] one persisted folder ignore (RES-12). The clips in it are
    offered again from the next poll, which is the point of the button."""
    def _do() -> None:
        try:
            forgotten = app.ignore_tracker.forget_folder(folder)
        except Exception:
            log.exception("settings: could not forget the folder ignore %s", folder)
            tray_mod._notify(app, f"CCSync could not undo that. {ui_copy.DIAGNOSTICS}.")
            return
        if forgotten:
            tray_mod._notify(app, f"CCSync will offer clips in {folder} again.")
        else:
            # "Could not check" must never render as "done": the entry was
            # already gone, and saying so is cheaper than a second click.
            tray_mod._notify(app, f"{folder} was not on the leave-alone list.")
    tray_mod._spawn(app, "Forget folder ignore", _do)


def _help_url(app: "CompanionApp", anchor: str = "") -> str:
    """Where HOW CC SYNC WORKS goes, or "" when nowhere.

    ui_copy.help_url is the one place the route is spelled (wave 4). The
    fallback exists because this window and that constant land in the same
    wave: a build whose ui_copy half is older still gets the button rather
    than losing the section."""
    url = ""
    builder = getattr(ui_copy, "help_url", None)
    if callable(builder):
        try:
            url = str(builder(getattr(app, "config", {}) or {}) or "")
        except Exception:
            log.exception("settings: could not build the help URL")
            url = ""
    if not url:
        base = str((getattr(app, "config", {}) or {}).get("dashboard_url", "")).strip()
        if not base:
            return ""
        url = base.rstrip("/") + str(getattr(ui_copy, "HELP_URL_PATH", "/help"))
    return url + anchor if url else ""


def action_open_help(app: "CompanionApp", anchor: str = "") -> None:
    """Open the help page in the default browser.

    Its own opener rather than tray's dashboard one: webbrowser.open()
    returns False with nothing logged when no browser could be launched
    (tray._open_dashboard's history), and the sentence an editor needs then
    names the help page, not the dashboard."""
    def _do() -> None:
        url = _help_url(app, anchor)
        if not url:
            tray_mod._notify(app, "This computer does not know where your "
                                  "dashboard is, so it cannot open the help page.")
            return
        log.info("settings: opening help at %s", url)
        launched = False
        try:
            import webbrowser

            launched = bool(webbrowser.open(url))
        except Exception:
            log.exception("settings: could not open %s", url)
        if not launched:
            log.warning("settings: no browser could be launched for %s", url)
            tray_mod._notify(app, f"Couldn't open a browser. The help page is at {url}")
    tray_mod._spawn(app, "Open the help page", _do)


def _rehearsal_mode() -> bool:
    """`fixer_dry_run` (RES-15). Read through fixer so the window and the
    thing it describes answer from the same cached value; never raises."""
    try:
        from . import fixer as fixer_mod

        return bool(fixer_mod.dry_run_default())
    except Exception:
        log.exception("settings: could not tell whether FIX ALL is rehearsing")
        return False


def action_turn_rehearsal_off(app: "CompanionApp") -> None:
    """[ TURN REHEARSAL OFF ] (RES-15). The key is cached once per process
    (fixer.dry_run_default), so the cache is dropped here as well as the
    line being written - otherwise the button would appear to do nothing
    until the next start, which is the shape APP-11 was."""
    def _do() -> None:
        try:
            saved = config_mod.set_value(config_mod.CONFIG_PATH, "fixer_dry_run", False)
        except Exception:
            log.exception("settings: could not turn fixer_dry_run off")
            tray_mod._notify(app, "Couldn't save that - see the log.")
            return
        if not saved:
            tray_mod._notify(app, "Couldn't save that - see the log.")
            return
        try:
            from . import fixer as fixer_mod

            fixer_mod.reset_dry_run_cache()
        except Exception:
            log.exception("settings: could not clear the rehearsal cache")
        tray_mod._notify(app, "FIX ALL will copy files in again.")
    tray_mod._spawn(app, "Turn rehearsal off", _do)


def _needs_p_repair(snap: dict, app: "CompanionApp", guard: dict) -> bool:
    """Whether to offer [ REPAIR P: NOW ] (UX-15).

    Two independent signals, because either alone misses a real case: the
    CACHED classification of the drive (the tray's own read, never a probe),
    and Resolve telling us it cannot resolve a canonical path this poll.
    """
    try:
        if not app.p_repair_available():
            return False
    except Exception:
        log.exception("settings: could not tell whether the drive can be repaired")
        return False
    if snap.get("p_mode") in ("other", "none"):
        return True
    try:
        return int(((guard or {}).get("resolve_health") or {}).get("bad_prefix") or 0) > 0
    except (TypeError, ValueError):
        return False


def action_put_project_back(app: "CompanionApp", subpath: str = "") -> None:
    """UX-3 (resilience sweep 2026-08-28): move a project folder the editor
    renamed or dragged back to where CCSync expects it.

    A click, never automatic: the folder in the wrong place is the one they
    have been working in. The move itself is `repath._move_dir`, which
    refuses when the target already exists and deletes nothing."""
    def _do() -> None:
        try:
            message = app.put_project_dir_back(subpath)
        except Exception:
            log.exception("settings: put_project_dir_back failed")
            message = "CCSync could not move that folder back. See the log."
        tray_mod._notify(app, message)
    tray_mod._spawn(app, "Put the project folder back", _do)


def action_clear_ingest_staging(app: "CompanionApp") -> None:
    """MEDIA-3: delete every finished ingest staging folder now.

    The answer to a space refusal that names a dot-folder inside the archive
    the editor has no other way to see. Only FINISHED batches: a running
    batch's staging, and a drop that has been staged but not run, are never
    candidates."""
    def _do() -> None:
        try:
            message = app.clear_finished_ingest_staging()
        except Exception:
            log.exception("settings: clear_finished_ingest_staging failed")
            message = "CCSync could not clear the staging folders. See the log."
        tray_mod._notify(app, message)
    tray_mod._spawn(app, "Clear finished staging", _do)


def _epoch(value) -> float:
    """Seconds since the epoch from an epoch number or an ISO timestamp, or
    0.0 when the value is neither. Never raises: a timestamp CCSync cannot
    read must cost the phrase, not the section."""
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime, timezone

        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except Exception:
        return 0.0


def age_phrase(value, now: float = 0.0) -> str:
    """"4 min ago" / "2 h ago" / "just now", or "" for a time we cannot
    read. Used for last_scan_at (RES-5) and a job's start (CMEDIA-2)."""
    stamp = _epoch(value)
    if not stamp:
        return ""
    seconds = max(0.0, (now or time.time()) - stamp)
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds // 60)} min ago"
    if seconds < 172800:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


_LANE_WORDS = {
    "idle": "up to date",
    "syncing": "syncing now",
    "queued": "waiting its turn",
    "paused": "paused",
    "error": "there is a problem",
    "off": "not synced to this computer",
    "skipped": "not synced to this computer",
}
# One vocabulary (sweep 2026-09-03 section 4, built 2026-09-04): the three
# transports are "upload" / "proxy download" / "folder sync" everywhere an
# editor reads them, and the word "lane" is in no visible string. The words
# come from ui_copy.LANE_WORDS, which is what the dashboard's own API speaks.
_LANE_TITLES = (("A", ui_copy.lane_words("A")),
                ("B", ui_copy.lane_words("B")),
                ("C", ui_copy.lane_words("C")))
# The section header these three live under. A constant because the jump
# strip (APP-17), the tests and four comments all name it.
SYNCING_SECTION = "SYNCING"


def _lane_words(state) -> str:
    key = str(state or "").strip().lower()
    return _LANE_WORDS.get(key, key or "not known")


# -- SYNC-117: the reminder can be turned off, for this episode only --------
#
# The only way out of a balloon every 30 minutes was the drive coming back or
# drive_reminder_minutes in a TOML file a frozen-exe editor has no reason to
# know exists. Neither button is a persistent opt-out: the warning LINE
# stays, the record stays, and the drive coming back clears both.
_SNOOZE_MINUTES = 120


def _drive_reminder(app: "CompanionApp"):
    """The running DriveReminder, or None. Private attribute on the app
    (app.py builds it in __init__); the public name is tried first so a
    later rename costs nothing here."""
    return getattr(app, "drive_reminder", None) or getattr(app, "_drive_reminder", None)


def _drive_reminder_items(app: "CompanionApp") -> list:
    """[ REMIND ME LATER ] / [ STOP REMINDING ME ABOUT THIS DRIVE ], while an
    episode is open."""
    reminder = _drive_reminder(app)
    try:
        if reminder is None or not reminder.active:
            return []
        muted = bool(getattr(reminder, "reminders_muted", False))
    except Exception:
        log.exception("settings: could not read the drive reminder")
        return []
    if muted:
        return [Line("Reminders about this drive are off until it is plugged "
                     "back in.", style="muted")]
    if not hasattr(reminder, "mute_episode"):
        return []
    return [
        Button("REMIND ME LATER",
               lambda: action_mute_drive_reminder(app, _SNOOZE_MINUTES)),
        Button("STOP REMINDING ME ABOUT THIS DRIVE",
               lambda: action_mute_drive_reminder(app, 0)),
    ]


def action_mute_drive_reminder(app: "CompanionApp", minutes: float) -> None:
    """Silence the reminder balloons without touching what is owed."""
    def _do() -> None:
        reminder = _drive_reminder(app)
        try:
            muted = bool(reminder is not None and reminder.mute_episode(minutes))
        except Exception:
            log.exception("settings: could not mute the drive reminder")
            tray_mod._notify(app, f"CCSync could not do that. {ui_copy.DIAGNOSTICS}.")
            return
        if not muted:
            # Nothing to mute must not render as "muted": the drive came
            # back between the render and the click.
            tray_mod._notify(app, "There is nothing to remind you about now.")
            return
        if minutes:
            tray_mod._notify(
                app, f"CCSync will remind you about this drive again in "
                     f"{ui_copy.count(int(minutes), 'minute')}.")
        else:
            tray_mod._notify(
                app, "CCSync will stop reminding you about this drive. Your "
                     "unfinished syncing is still waiting for it, and Settings "
                     "still says so.")
    tray_mod._spawn(app, "Mute the drive reminder", _do)


def _projects_section(app: "CompanionApp") -> list:
    """PROJECTS ON THIS COMPUTER (SYNC-107, sweep 2026-09-03).

    The only enumeration of this machine's plan used to be the stack of
    REMOVE buttons in ADVANCED, which is also the sole place the words
    "upload only" appeared to an editor: inside the label of the button that
    deletes the project. Consumed through getattr because the sequencer
    grew project_status() in the same wave; an app without it renders no
    section at all rather than an empty one."""
    sequencer = getattr(app, "sequencer", None)
    reader = getattr(sequencer, "project_status", None)
    if not callable(reader):
        return []
    try:
        projects = list(reader() or [])
    except Exception:
        log.exception("settings: could not read this computer's project list")
        return []
    if not projects:
        return [Line("No projects are ticked for this computer yet: tick them on "
                     "the dashboard")]
    items: list = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        slug = str(project.get("slug") or "").strip() or "a project"
        mode = "upload only (no proxy download)" \
            if str(project.get("mode") or "").strip().lower() == "upload_only" \
            else "full sync"
        state = str(project.get("state") or "").strip()
        head = f"{slug} - {mode}"
        if state:
            head += f": {_lane_words(state)}"
        items.append(Line(head))
        lanes = project.get("lanes") or {}
        if isinstance(lanes, dict):
            parts = [f"{title} {_lane_words(lanes[key])}"
                     for key, title in _LANE_TITLES if lanes.get(key)]
            if parts:
                items.append(Line("  " + ", ".join(parts), style="muted"))
        detail = str(project.get("detail") or "").strip()
        if detail:
            items.append(Line(f"  {detail}", style="muted"))
    return items


def _resolve_section(app: "CompanionApp", guard: dict) -> list:
    """RESOLVE (RES-5, sweep 2026-09-03).

    Every number here was already computed each poll and rendered only into a
    diagnostics bundle nobody opens unprompted: an editor with 40 dead links
    and 12 unattachable proxies had no number anywhere in the UI. `health`
    may be the older shape (counts only), so every key is optional and an
    absent one renders nothing."""
    reader = getattr(app, "resolve_health", None)
    health = None
    if callable(reader):
        try:
            health = reader()
        except Exception:
            log.exception("settings: could not read the Resolve health")
            health = None
    if not isinstance(health, dict):
        health = (guard or {}).get("resolve_health")
    if not isinstance(health, dict) or not health:
        return []

    items: list = []
    connected = health.get("connected")
    if connected is False:
        items.append(Line("Not connected to Resolve right now", style="warning"))
    elif connected is True:
        items.append(Line("Connected to Resolve"))
    try:
        wedged = float(health.get("wedged_seconds") or 0)
    except (TypeError, ValueError):
        wedged = 0.0
    if wedged > 20:
        call = str(health.get("wedged_call") or "a call")
        items.append(Line(
            f"Resolve has not answered {call} for {int(wedged)}s. Nothing is "
            "wrong with your sync; Resolve itself is busy", style="warning"))
    project = health.get("project_open") or health.get("open_project")
    if project:
        items.append(Line(f"Project open: {project}"))
    elif health.get("project_open") is False:
        items.append(Line("No project is open in Resolve"))

    scanned = age_phrase(health.get("last_scan_at"))
    counts = (
        ("out_of_tree", "{n} clip(s) are stored outside your synced folder, so "
                        "nothing is backing them up"),
        ("missing", "{n} clip(s) in this project are offline"),
        ("bad_prefix", "{n} clip(s) point at a drive letter this computer does "
                       "not have"),
        ("non_canonical_refused", "{n} clip(s) were left alone: their path is "
                                  "not one CCSync may rewrite"),
    )
    offered_scan = False
    for key, template in counts:
        try:
            count = int(health.get(key) or 0)
        except (TypeError, ValueError):
            continue
        # A zero with no scan behind it means "we have not looked", never
        # "nothing is wrong" (resolve_health's own docstring) -- so the
        # counts are shown only alongside a scan time.
        if not count or not scanned:
            continue
        items.append(Line(template.format(n=count), style="warning"))
        if not offered_scan:
            items.append(Button("SCAN WHOLE PROJECT",
                                lambda: tray_mod.action_scan_whole_project(app)))
            offered_scan = True

    attach = health.get("proxy_attach") or {}
    if isinstance(attach, dict) and (attach.get("attached") or attach.get("failed")):
        line = (f"Proxies attached to clips: {int(attach.get('attached') or 0)}")
        failed = int(attach.get("failed") or 0)
        if failed:
            why = str(attach.get("why") or "").strip()
            line += f", {failed} could not be attached" + (f": {why}" if why else "")
        items.append(Line(line, style="warning" if failed else "normal"))
    gaps = health.get("proxy_gaps") or {}
    if isinstance(gaps, dict):
        for key, phrase in (("low_space", "this disk is low on space"),
                            ("capped", "this computer's proxy limit was reached"),
                            ("truncated", "the list was too long to finish")):
            try:
                count = int(gaps.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if count:
                items.append(Line(f"{count} proxies skipped: {phrase}", style="warning"))
    stills = health.get("stills") or {}
    if isinstance(stills, dict) and stills.get("instruction"):
        items.append(Line(str(stills["instruction"]),
                          style="normal" if stills.get("ok") else "warning"))
    if scanned:
        items.append(Line(f"Checked {scanned}", style="muted"))

    undo = getattr(app, "undo_last_fix_available", None)
    try:
        can_undo = bool(undo()) if callable(undo) else False
    except Exception:
        log.exception("settings: could not tell whether the last fix can be undone")
        can_undo = False
    if can_undo:
        items.append(Button("UNDO LAST FIX", lambda: action_undo_last_fix(app)))
    return items


def action_undo_last_fix(app: "CompanionApp") -> None:
    """[ UNDO LAST FIX ] (RES-5/RES-13). app.undo_last_fix() when the app
    carries it; the ADVANCED button's action is what shipped before it."""
    undo = getattr(app, "undo_last_fix", None)
    if callable(undo):
        tray_mod._spawn(app, "Undo the last fix", undo)
        return
    tray_mod.action_undo_last_relink(app)


def action_stop_current_job(app: "CompanionApp") -> None:
    """[ STOP THIS JOB ] (CMEDIA-2). The same should_stop path an admin's
    cancel uses: the child is killed and the result posted as cancelled, not
    retryable. False means there was nothing to stop, which must not render
    as "stopped"."""
    def _do() -> None:
        stopper = getattr(app, "stop_current_job", None)
        if not callable(stopper):
            tray_mod._notify(app, "This build cannot stop a fleet job.")
            return
        try:
            stopped = stopper()
        except Exception:
            log.exception("settings: could not stop the running fleet job")
            tray_mod._notify(app, f"CCSync could not stop that job. {ui_copy.DIAGNOSTICS}.")
            return
        tray_mod._notify(
            app, "Stopping the fleet job. It goes back to the queue for another "
                 "computer." if stopped else "There is no fleet job running now.")
    tray_mod._spawn(app, "Stop the fleet job", _do)


# -- SYS-8 / UX-11: the fleet-jobs settings are controls, not a TOML file ----
#
# Three per-computer keys (`jobs_enabled`, `jobs_kinds`,
# `jobs_volunteer_minutes`) whose only interface was "remote into that
# machine and edit ~/.ccsync/config.toml". They are written through
# config_mod.set_value, the same one-key line patch the role switch uses, and
# every one of them is read at construction (jobs_runner.JobsRunner.__init__,
# capabilities.snapshot), so every one of them needs a restart to apply -
# which the section says on the line, exactly as the role does.
#
# `cards_agent` is deliberately NOT here: exactly one computer in a fleet may
# run the Timeline Cards agent, and the server is the only party that can see
# all of them (SYS-8 (b)).
_VOLUNTEER_CHOICES = (15, 30, 60, 120)


def _config_on_disk() -> dict:
    """config.toml as it will be read at the next start. Never raises: an
    unreadable file costs the current values, not the window."""
    try:
        return dict(config_mod.load_config(config_mod.CONFIG_PATH) or {})
    except Exception:
        log.exception("settings: could not read config.toml")
        return {}


def _setting_changed(app: "CompanionApp", cfg: dict, key: str, default) -> bool:
    """Whether the value on disk differs from the one THIS process started
    with - the same test _mode_needs_restart makes, for the same reason: a
    write to config.toml never mutates the live config. `cfg` is the file
    read once by the caller: this runs on every render, twice a second."""
    try:
        on_disk = (cfg or {}).get(key, default)
        current = (getattr(app, "config", {}) or {}).get(key, default)
        return str(on_disk).strip().lower() != str(current).strip().lower()
    except Exception:
        log.exception("settings: could not compare %s with the running value", key)
        return False


def action_write_setting(app: "CompanionApp", key: str, value, sentence: str) -> None:
    """Write one config.toml key and say what it will take.

    Reopens the window afterwards (action_show_all_advisories' precedent):
    every button here closes it first, and a checkbox whose window vanishes
    reads as a click that went nowhere."""
    def _do() -> None:
        try:
            saved = config_mod.set_value(config_mod.CONFIG_PATH, key, value)
        except Exception:
            log.exception("settings: could not write %s=%r to config.toml", key, value)
            tray_mod._notify(app, "Couldn't save that - see the log.")
            return
        if not saved:
            # APP-11: a write that cannot be read back is not a save.
            tray_mod._notify(app, "Couldn't save that - see the log.")
            return
        tray_mod._notify(app, sentence)
        show_settings(app)
    tray_mod._spawn(app, f"Save {key}", _do)


def _fleet_jobs_controls(app: "CompanionApp") -> list:
    """The three settings, as rows the existing renderer already draws.

    A checkbox is a Button whose label carries its own state ("[x] ..."):
    the model has Lines and Buttons and nothing else, and a new widget type
    would be a change to the Tk half for a control that reads perfectly well
    as text in a monospace window."""
    cfg = _config_on_disk()
    items: list = []
    enabled = bool(cfg.get("jobs_enabled", True))
    items.append(Button(
        f"[{'x' if enabled else ' '}] Let the fleet use this computer",
        lambda: action_write_setting(
            app, "jobs_enabled", not enabled,
            "This computer will take work for the fleet again."
            if not enabled else
            "This computer will stop taking work for the fleet. Takes effect "
            "the next time CCSync starts.")))
    items.append(Line("  Fleet work runs only while you are away from this "
                      "computer.", style="muted"))

    from . import capabilities as capabilities_mod

    kinds = list(getattr(capabilities_mod, "KNOWN_KINDS", ()) or ())
    try:
        allowed = list(capabilities_mod.job_kinds(cfg))
    except Exception:
        log.exception("settings: could not read this computer's job kinds")
        allowed = []
    for kind in kinds:
        # An empty allow-list means EVERY kind (capabilities.job_kinds), so
        # an unticked box is only ever an explicit exclusion.
        on = (not allowed) or kind in allowed
        if on:
            remaining = [k for k in kinds if k != kind and ((not allowed) or k in allowed)]
        else:
            remaining = [k for k in kinds if k in allowed or k == kind]
        # All of them ticked is written as "", not as the full list: a build
        # that learns a new kind later must not find this computer excluded
        # from it by a list nobody knew they were writing.
        value = "" if len(remaining) == len(kinds) else ", ".join(remaining)
        items.append(Button(
            f"  [{'x' if on else ' '}] {_kind_label(kind)}",
            (lambda kind=kind, value=value, on=on, remaining=remaining:
             action_set_job_kind(app, kind, value, on, remaining))))

    minutes = _volunteer_minutes(cfg)
    nxt = _next_volunteer_choice(minutes)
    items.append(Button(
        f"LEND THIS COMPUTER FOR {ui_copy.count(minutes, 'minute')} AT A TIME "
        f"(click for {nxt})",
        lambda: action_write_setting(
            app, "jobs_volunteer_minutes", nxt,
            f"One click of 'Take fleet jobs now' will lend this computer for "
            f"{ui_copy.count(nxt, 'minute')}. Takes effect the next time "
            f"CCSync starts.")))
    changed = [k for k in ("jobs_enabled", "jobs_kinds", "jobs_volunteer_minutes")
               if _setting_changed(app, cfg, k, config_mod.DEFAULTS.get(k))]
    if changed:
        items.append(Line(
            "The settings above were changed and take effect when CCSync next "
            "starts.", style="warning"))
    return items


def _kind_label(kind: str) -> str:
    """The kinds in editor English. Unknown kinds keep their own name rather
    than being hidden: a build that grows one must still offer the box."""
    return {
        "whisper": "Transcribe audio (uses the graphics card)",
        "proxy-480p": "Make small preview copies of video",
        "audio-extract": "Pull the audio out of video",
        "peaks": "Draw audio waveforms",
    }.get(kind, kind)


def _volunteer_minutes(cfg: dict) -> int:
    try:
        value = int(float(cfg.get("jobs_volunteer_minutes", 30) or 30))
    except (TypeError, ValueError):
        value = 30
    return value if value > 0 else 30


def _next_volunteer_choice(minutes: int) -> int:
    """The next value the button offers, wrapping. A cycle rather than a
    text field: the window has no text entry, and four choices cover what
    "lend this computer" ever means."""
    if minutes in _VOLUNTEER_CHOICES:
        index = _VOLUNTEER_CHOICES.index(minutes)
        return _VOLUNTEER_CHOICES[(index + 1) % len(_VOLUNTEER_CHOICES)]
    return _VOLUNTEER_CHOICES[0]


def action_set_job_kind(app: "CompanionApp", kind: str, value: str,
                        was_on: bool, remaining: list) -> None:
    """Tick or untick ONE job kind (SYS-8).

    Unticking the last one is refused: `jobs_kinds = ""` means every kind
    (capabilities.job_kinds), so "none of them" cannot be written here at
    all, and a machine that silently took every kind when its editor had
    just unticked the last one would be the exact opposite of the click."""
    if was_on and not remaining:
        tray_mod._notify(
            app, "That is the last kind of work this computer takes. Untick "
                 "'Let the fleet use this computer' instead.")
        return
    action_write_setting(
        app, "jobs_kinds", value,
        f"This computer will {'no longer ' if was_on else ''}take "
        f"{_kind_label(kind).lower()} for the fleet. Takes effect the next "
        "time CCSync starts.")


def _jobs_section(app: "CompanionApp") -> list:
    """JOBS (CMEDIA-2, sweep 2026-09-03).

    The tray offered exactly one job control and no way to see, stop or
    review the work this machine does for everybody else."""
    reader = getattr(app, "jobs_status", None)
    if not callable(reader):
        return []
    try:
        status = reader()
    except Exception:
        log.exception("settings: could not read the fleet job status")
        return []
    if not isinstance(status, dict) or not status:
        return []

    items: list = []
    gate = status.get("gate") or {}
    if isinstance(gate, dict) and gate:
        if gate.get("taking_work"):
            items.append(Line("Taking fleet work"))
        else:
            reason = str(gate.get("reason") or "").strip()
            items.append(Line("Not taking work" + (f": {reason}" if reason else "")))

    current = status.get("current") or {}
    if isinstance(current, dict) and current.get("id"):
        kind = str(current.get("kind") or "a job")
        rel = str(current.get("rel_path") or "").strip()
        started = age_phrase(current.get("started_at"))
        line = f"Running a fleet job for the team: {kind}"
        if rel:
            line += f" on {rel}"
        if started:
            line += f" (started {started})"
        items.append(Line(line))
        forced = str(current.get("forced_reason") or "").strip()
        if forced:
            items.append(Line(f"  {forced}", style="muted"))
        items.append(Button("STOP THIS JOB", lambda: action_stop_current_job(app)))

    recent = status.get("recent") or []
    if isinstance(recent, list):
        for entry in [e for e in recent if isinstance(e, dict)][:10]:
            kind = str(entry.get("kind") or "job")
            rel = str(entry.get("rel_path") or "").strip()
            outcome = str(entry.get("outcome") or "").strip() or "finished"
            finished = age_phrase(entry.get("finished_at"))
            line = f"  {kind}" + (f" on {rel}" if rel else "") + f": {outcome}"
            if finished:
                line += f", {finished}"
            error = str(entry.get("error") or "").strip()
            if error:
                line += f" ({error})"
            items.append(Line(line, style="muted"))
    return items


def build_settings_model(snap: dict, app: "CompanionApp") -> list[Section]:
    """Pure: snapshot + app -> the sections the window renders. No tkinter."""
    sections: list[Section] = []

    # -- [ THIS COMPUTER ] ---------------------------------------------------
    current_role = app.effective_mode() if hasattr(app, "effective_mode") else "editor"
    computer_items: list = [
        Line(f"Computer name: {platform.node()}"),
        Line(f"Current role: {_role_label(current_role)}"),
        Button(
            "REMOTE EDITOR" + ("  (current)" if current_role != "base" else ""),
            lambda: action_set_role(app, "editor"),
        ),
        Line("  syncs projects to this computer's own drive", style="muted"),
        Button(
            "WIRED TO THE SERVER" + ("  (current)" if current_role == "base" else ""),
            lambda: action_set_role(app, "base"),
        ),
        Line("  works directly off the server share, so nothing is synced "
             "to it", style="muted"),
    ]
    if _mode_needs_restart(app):
        computer_items.append(Line(
            "The role above was changed and takes effect when CCSync next "
            "starts.", style="warning",
        ))
    computer_items.append(Line(str(snap.get("identity_label", ""))))
    guard = snap.get("sync_guard") or {}
    if _credential_refused(guard):
        # APP-8: identity.valid() is local, so a revoked token still reads as
        # signed in and this section offered SIGN OUT and nothing else. The
        # editor's correct move is to sign in again, and nothing said so.
        computer_items.append(Line(
            "⚠ The server rejected this computer's sign-in, so your admin "
            "cannot see whether you are syncing.", style="warning"))
        computer_items.append(Button("SIGN IN AGAIN…", lambda: action_sign_in_again(app)))
    if snap.get("signed_in"):
        computer_items.append(Button("SIGN OUT", lambda: tray_mod.action_sign_out(app)))
    else:
        computer_items.append(Button("SIGN IN…", lambda: tray_mod.action_sign_in(app)))
    # APP-13: unconditional. Three separate pieces of copy tell an editor to
    # restart the companion, and the button that does it used to appear only
    # after a role change nobody has made.
    computer_items.append(Button("RESTART CCSYNC NOW", lambda: action_restart(app)))
    sections.append(Section("THIS COMPUTER", computer_items))

    # -- [ SYNCING ] ---------------------------------------------------------
    lane_items: list = [
        Line(tray_mod._format_lane_line_from(
            s, paused=bool(snap.get("paused")), problems=bool(snap.get("problems")),
            root_absent=bool(snap.get("root_absent")),
            # SYNC-105 (sweep 2026-09-04): which way the drive is gone, so
            # these three lines say the same thing as the balloon and the
            # tray line rather than "disconnected" about a plugged-in drive.
            root_state=snap.get("root_state"),
        ))
        for s in snap.get("statuses", [])
    ]
    for text in (snap.get("sequencer_line"), snap.get("current_project_line")):
        if text:
            lane_items.append(Line(text))
    # APP-9: the licence refusal, with its own action, ABOVE the ranked
    # advisories -- one click here is what the sentence used to send the
    # editor back through an installer wizard for.
    licence_text = _licence_advisory(guard)
    if licence_text:
        lane_items.append(Line(licence_text, style="warning"))
        lane_items.append(Button("READ AND ACCEPT THE LICENCE",
                                 lambda: action_accept_licence(app)))
    # SYNC-118: ranked, collapsed and capped. The producers and their order
    # inside a tier are unchanged; what is new is that the halt is above the
    # size of the recoverable trash instead of beside it.
    advisories = _lane_advisories(guard, skip_blocked=bool(licence_text))
    show_all = advisories_shown_in_full()
    ranked, hidden = rank_advisories(advisories, show_all)
    lane_items.extend(ranked)
    if hidden:
        lane_items.append(Line(f"and {hidden} more", style="muted"))
        lane_items.append(Button("SHOW ALL",
                                 lambda: action_show_all_advisories(app, True)))
    elif show_all and len(advisories) > _ADVISORY_CAP:
        lane_items.append(Button("SHOW FEWER",
                                 lambda: action_show_all_advisories(app, False)))
    if snap.get("root_unfinished"):
        # CR-92: the drive went out with work owed. The balloon says it
        # every half hour; this is where it stays readable in between.
        lane_items.append(Line(
            f"Your drive was disconnected with {snap['root_unfinished']} still to "
            f"go - plug it back in to finish syncing", style="warning"))
    lane_items.extend(_drive_reminder_items(app))
    if snap.get("ytdl_line"):
        lane_items.append(Line(snap["ytdl_line"]))

    if ((guard.get("lane_b_breaker") or {}).get("tripped")
            # The same button clears a free-space park (SYS-5 / SYNC-7).
            or (guard.get("disk_floor") or {}).get("parked")):
        lane_items.append(Button(
            "RESUME PROXY DOWNLOAD", lambda: tray_mod.action_resume_lane_b(app, snap)))
    # UX-3 (resilience sweep 2026-08-28): a project folder that was here last
    # pass and has gone. The button is offered only when the marker was
    # actually found somewhere on this machine -- an offer to move a folder we
    # cannot see would be a button that can only fail.
    moved = [m for m in (guard.get("moved_project_dirs") or []) if isinstance(m, dict)]
    for entry in moved[:5]:
        label = str(entry.get("subpath") or "").rstrip("/").split("/")[-1] \
            or str(entry.get("slug") or "a project")
        lane_items.append(Line(
            f"'{label}' is not where CCSync expects it - nothing in it is "
            "reaching the server", style="warning"))
        if entry.get("found"):
            lane_items.append(Line(f"  found at {entry['found']}", style="muted"))
            lane_items.append(Button(
                f"PUT '{label}' BACK WHERE CCSYNC EXPECTS IT",
                (lambda sub=str(entry.get("subpath") or ""):
                 action_put_project_back(app, sub))))
    strays = guard.get("stray_projects") or {}
    if strays.get("count"):
        # SYNC-10: reported, never deleted -- the same posture as the orphan
        # .partial scan. No button on purpose.
        lane_items.append(Line(
            f"{strays['count']} project folder(s) on this computer are in no "
            f"sync plan ({int(strays.get('bytes') or 0) / 1e9:.1f} GB). Nothing "
            "syncs them and CCSync will not delete them", style="warning"))
    staging = guard.get("ingest_staging") or {}
    if staging.get("bytes"):
        # MEDIA-3: staging lives in a dot-folder inside the archive, so
        # without this line the disk it fills is unattributable.
        lane_items.append(Line(
            f"Finished indexing staging is holding "
            f"{int(staging['bytes']) / 1e9:.1f} GB on this computer",
            style="warning"))
        lane_items.append(Button(
            "CLEAR FINISHED STAGING", lambda: action_clear_ingest_staging(app)))

    halt_active = bool((guard.get("halt") or {}).get("active"))
    halt_is_fleet = (guard.get("halt") or {}).get("scope") == "fleet"
    if halt_active and not halt_is_fleet:
        lane_items.append(Button(
            "START SYNCING AGAIN", lambda: tray_mod.action_release_halt(app)))

    proxy_gap = snap.get("proxy_gap") or {}
    for text in tray_mod.proxy_advisory_lines(proxy_gap):
        lane_items.append(Line(text))
    proxy_missing = int(proxy_gap.get("missing") or 0)
    proxy_encoding = bool(proxy_gap.get("encoding"))
    if proxy_encoding:
        lane_items.append(Button(
            "STOP MAKING PROXIES", lambda: tray_mod.action_stop_proxies(app)))
        lane_items.append(Button(
            "SHOW PROXY PROGRESS", lambda: tray_mod.action_show_proxy_progress(app)))
    elif proxy_missing and proxy_gap.get("can_generate"):
        lane_items.append(Button(
            "MAKE PROXIES NOW (don't wait until I'm away)",
            lambda: tray_mod.action_make_proxies(app)))
    if proxy_gap.get("can_generate") or tray_mod._proxy_history(proxy_gap).get("last_at"):
        lane_items.append(Button(
            "PROXIES THIS COMPUTER HAS MADE…", lambda: tray_mod.action_proxy_history(app)))

    broll = snap.get("broll_ingest") or {}
    for text in tray_mod._ingest_lines(broll):
        lane_items.append(Line(text))
    if broll.get("batch_uid"):
        if broll.get("paused"):
            lane_items.append(Button(
                "RESUME B-ROLL INDEXING", lambda: tray_mod.action_resume_broll_ingest(app)))
        else:
            if broll.get("gate") in ("user-active", "resolve-open"):
                lane_items.append(Button(
                    "INDEX B-ROLL NOW (don't wait until I'm away)",
                    lambda: tray_mod.action_index_broll_now(app)))
            lane_items.append(Button(
                "PAUSE B-ROLL INDEXING", lambda: tray_mod.action_pause_broll_ingest(app)))
        lane_items.append(Button(
            "SHOW B-ROLL INDEXING PROGRESS",
            lambda: tray_mod.action_show_ingest_progress(app)))
        lane_items.append(Button(
            "CANCEL THE B-ROLL BATCH…", lambda: tray_mod.action_cancel_broll_ingest(app)))

    music = snap.get("music_ingest") or {}
    for text in tray_mod._ingest_lines(music, "music", "track"):
        lane_items.append(Line(text))
    if music.get("batch_uid"):
        if music.get("paused"):
            lane_items.append(Button(
                "RESUME MUSIC INDEXING", lambda: tray_mod.action_resume_music_ingest(app)))
        else:
            if music.get("gate") in ("user-active", "resolve-open"):
                lane_items.append(Button(
                    "INDEX MUSIC NOW (don't wait until I'm away)",
                    lambda: tray_mod.action_index_music_now(app)))
            lane_items.append(Button(
                "PAUSE MUSIC INDEXING", lambda: tray_mod.action_pause_music_ingest(app)))
        lane_items.append(Button(
            "SHOW MUSIC INDEXING PROGRESS",
            lambda: tray_mod.action_show_music_ingest_progress(app)))
        lane_items.append(Button(
            "CANCEL THE MUSIC BATCH…", lambda: tray_mod.action_cancel_music_ingest(app)))

    sections.append(Section(SYNCING_SECTION, lane_items))

    # -- [ YOUTUBE ] ------------------------------------------------------
    if snap.get("ytdl_local_downloads") or snap.get("ytdl_youtube_signin"):
        yt_items: list = []
        # CYT-7 (usability sweep 2026-09-03): FIRST, because a downloader
        # that cannot update itself is the thing that will make the buttons
        # below stop working, and the editor is the only person on this
        # machine who can see it.
        ytdlp_line = tray_mod.ytdlp_warning_line(snap.get("ytdlp_status"))
        if ytdlp_line:
            yt_items.append(Line(ytdlp_line, style="warning"))
        if snap.get("ytdl_local_downloads"):
            yt_items.append(Button(
                "Accept YouTube Terms ✓" if snap.get("ytdl_attested")
                else "Accept YouTube Terms…",
                lambda: tray_mod.action_youtube_terms(app),
            ))
        if snap.get("ytdl_youtube_signin"):
            yt_health = (snap.get("ytdl_cookies_health") or {}).get("status")
            yt_bad = yt_health in (ytdl_cookies.STATUS_STALE, ytdl_cookies.STATUS_EXPIRED)
            yt_signed_in = yt_health == ytdl_cookies.STATUS_OK
            if yt_bad:
                yt_items.append(Line(tray_mod._youtube_warning_line(snap), style="warning"))
                yt_label = "Sign in to YouTube again (session expired)…"
            elif yt_signed_in:
                yt_label = "YouTube: signed in ✓ (sign in again…)"
            else:
                yt_label = "Sign in to YouTube (for downloads)…"
            yt_items.append(Button(yt_label, lambda: tray_mod.action_youtube_sign_in(app)))
            yt_items.append(Button(
                "Use an exported cookies.txt…",
                lambda: tray_mod.action_youtube_cookies_file(app)))
        sections.append(Section("YOUTUBE", yt_items))

    # -- [ PROJECTS ] / [ RESOLVE ] / [ JOBS ] ------------------------------
    # Wave 3 of the 2026-09-03 sweep: the machine already knew every fact in
    # these three sections. Each renders only when its producer exists, so a
    # build whose app half is older simply does not draw it.
    project_items = _projects_section(app)
    if project_items:
        sections.append(Section("PROJECTS ON THIS COMPUTER", project_items))
    resolve_items = _resolve_section(app, guard)
    if resolve_items:
        sections.append(Section("RESOLVE", resolve_items))
    # SYS-8: the status half (CMEDIA-2) and the settings half under ONE
    # header. Two sections about the same subject, one of them named JOBS and
    # one FLEET JOBS, is the shape the vocabulary work exists to stop.
    job_items = _jobs_section(app) + _fleet_jobs_controls(app)
    if job_items:
        sections.append(Section("FLEET JOBS", job_items))

    # -- [ ADVANCED ] -------------------------------------------------------
    advanced_items: list = [
        Button("SCAN WHOLE PROJECT", lambda: tray_mod.action_scan_whole_project(app)),
        Button("BRING AN EXISTING PROJECT'S MEDIA INTO THE SYNCED FOLDER…",
               lambda: tray_mod.action_consolidate_project(app)),
        Button("UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE…",
               lambda: tray_mod.action_undo_last_relink(app)),
    ]
    # RES-15: FIX ALL copies nothing on this computer, and until now the only
    # sign of it was a batch that reported every clip as failed.
    if _rehearsal_mode():
        from . import popup as popup_mod

        advanced_items.append(Line(popup_mod.REHEARSAL_WARNING, style="warning"))
        advanced_items.append(Button("TURN REHEARSAL OFF",
                                     lambda: action_turn_rehearsal_off(app)))
    if _needs_p_repair(snap, app, guard):
        # UX-15: above the grade swap on purpose. This is the broken state
        # the toast fires about; the swap below is a thing the editor chose.
        letter = app.canonical_prefix_label()
        advanced_items.append(Line(
            f"Resolve is looking for your media on {letter} but {letter} is not "
            "pointing at your synced folder, so clips will show offline. Your "
            "uploads and downloads are still running.", style="warning"))
        advanced_items.append(Button(
            f"REPAIR {letter} NOW", lambda: action_repair_p_mapping(app)))
    for entry in _ignored_folders(app):
        folder = str(entry.get("folder") or "")
        reason = str(entry.get("reason") or "")
        advanced_items.append(Line(
            f"Leaving clips in {folder} alone"
            + (f" ({reason})" if reason else ""), style="muted"))
        advanced_items.append(Button(
            f"FORGET: {folder}",
            (lambda folder=folder: action_forget_ignored_folder(app, folder))))
    if snap.get("p_swap_available"):
        # SYNC-103 (sweep 2026-09-04): the letter is site data, and these
        # two labels are what ui_copy.finish_grading() quotes back at the
        # editor from the confirm dialog.
        swap_letter = tray_mod._canonical_letter(app)
        advanced_items.append(Button(
            f"FINISH GRADING: {swap_letter} BACK TO LOCAL PROXIES"
            if snap.get("p_mode") == "server"
            else f"GRADE FROM SERVER ORIGINALS (SWAP {swap_letter})…",
            lambda: tray_mod.action_grade_swap(app, snap),
        ))
    if not halt_active:
        advanced_items.append(Button(
            "STOP ALL SYNCING ON THIS COMPUTER…", lambda: tray_mod.action_halt_sync(app)))
    for proj in snap.get("removable", []):
        slug = proj.get("slug", "")
        rel = proj.get("rel", "")
        label = (
            "REMOVE '" + rel.split("/")[-1] + "'"
            + (" (upload only)" if proj.get("upload_only") else "")
            + " FROM THIS COMPUTER…"
        )
        advanced_items.append(Button(
            label, (lambda slug=slug, rel=rel: tray_mod.action_remove_project(app, slug, rel))))
    sections.append(Section("ADVANCED", advanced_items))

    # -- [ HELP ] -------------------------------------------------------
    help_items: list = [
        Button("COPY DIAGNOSTICS FOR YOUR ADMIN",
               lambda: tray_mod.action_copy_diagnostics(app)),
        Button("OPEN LOG", lambda: tray_mod.action_open_log(app)),
    ]
    # UX-3 / SYS-21 (a): until now the HELP section contained no help. Both
    # buttons open the ONE document, served by the dashboard; hidden when
    # this computer has no dashboard URL, because a button that can only
    # fail is worse than a section with two rows in it.
    if _help_url(app):
        help_items.append(Button("HOW CC SYNC WORKS",
                                 lambda: action_open_help(app)))
        help_items.append(Button("WHAT DO THESE MEAN?",
                                 lambda: action_open_help(app, "#glossary")))
    upgrade_info = snap.get("upgrade_info")
    if upgrade_info:
        help_items.append(Button(
            upgrade_mod.offer_label(upgrade_info["version"]),
            lambda: tray_mod.action_update_now(app)))
    help_items.append(Line(f"ccsync-companion v{config_mod.VERSION}", style="muted"))
    sections.append(Section("HELP", help_items))

    return _help_first(sections)


def _help_first(sections: list[Section]) -> list[Section]:
    """APP-17: HELP goes to the TOP whenever anything on this render is a
    warning.

    Eight of the advisory lines above instruct the reader to press [ COPY
    DIAGNOSTICS FOR YOUR ADMIN ], and on a computer with something wrong the
    SYNCING section alone is taller than the window, so that button was
    below two sections the reader had to scroll past to find it. On a healthy
    computer nothing moves: HELP stays where it has always been."""
    warned = any(isinstance(item, Line) and item.style == "warning"
                 for section in sections for item in section.items)
    if not warned:
        return sections
    ordered = [s for s in sections if s.title == "HELP"]
    if not ordered:
        return sections
    return ordered + [s for s in sections if s.title != "HELP"]


# -- the Tk shell -------------------------------------------------------

def _window_title() -> str:
    """UX-4: a function for the same reason drive_reminder.notify_title is."""
    return site_mod.notify_title("SETTINGS")
_REFRESH_MS = 2000


def show_settings(app: "CompanionApp") -> None:
    """Open the Settings window. Takes `_popup_active_lock` like every other
    tk.Tk() site in this process (see the module docstring)."""
    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        tray_mod._notify(app, "Another CCSync window is already open. Close it first.")
        return

    def _build_and_show() -> None:
        _build_settings_window(app, lock)

    try:
        from . import ui_dispatch

        ui_dispatch.dispatch(_build_and_show)
    except Exception as exc:
        log.warning("settings window unavailable (%s)", exc)
        if lock is not None and lock.locked():
            lock.release()


def _build_settings_window(app: "CompanionApp", lock) -> None:
    try:
        import tkinter as tk
        from tkinter import ttk

        from . import theme
    except Exception as exc:
        log.warning("settings window: tkinter unavailable (%s)", exc)
        if lock is not None and lock.locked():
            lock.release()
        return

    try:
        root = tk.Tk()
    except Exception as exc:
        log.warning("settings window failed to open (%s)", exc)
        if lock is not None and lock.locked():
            lock.release()
        return

    state = {"closed": False}

    def _release_and_close() -> None:
        if state["closed"]:
            return
        state["closed"] = True
        try:
            root.after_cancel(refresh_job[0]) if refresh_job[0] is not None else None
        except Exception:
            pass
        try:
            root.destroy()
        finally:
            if lock is not None and lock.locked():
                lock.release()

    def _run(label: str, fn: Callable[[], None]) -> Callable[[], None]:
        # ONE rule for every button: close this window, release the lock,
        # THEN run the action on its own thread. See the module docstring.
        def _handler() -> None:
            _release_and_close()
            tray_mod._spawn(app, label, fn)
        return _handler

    root.title(_window_title())
    theme.apply_window_icon(tk, root)
    root.configure(bg=theme.BG)
    root.geometry("720x640")
    root.minsize(560, 420)
    root.protocol("WM_DELETE_WINDOW", _release_and_close)
    root.bind("<Escape>", lambda _e: _release_and_close())

    # APP-17: the jump strip lives OUTSIDE the canvas, so it does not scroll
    # away from the reader who needs it. Packed before the canvas because
    # pack order is what puts it at the top.
    strip = tk.Frame(root, bg=theme.BG, padx=18, pady=6)
    strip.pack(side="top", fill="x")

    canvas = tk.Canvas(root, bg=theme.BG, highlightthickness=0)
    vbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    body = tk.Frame(canvas, bg=theme.BG, padx=18, pady=14)
    body_window = canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")

    def _on_body_configure(_e=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event) -> None:
        canvas.itemconfigure(body_window, width=event.width)

    body.bind("<Configure>", _on_body_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event) -> None:
        delta = -1 if event.delta > 0 else 1
        canvas.yview_scroll(delta, "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _jump_to(header) -> None:
        """Scroll so `header` is at the top. Measured at CLICK time: the
        window rebuilds itself every two seconds and a y captured at render
        would point at whatever has since grown above it.

        Not subject to the module docstring's "every button closes the
        window" rule: this one opens nothing, spawns nothing and changes
        nothing, and closing the window to scroll it would be absurd."""
        try:
            body.update_idletasks()
            height = max(1, body.winfo_height())
            canvas.yview_moveto(max(0.0, min(1.0, header.winfo_y() / height)))
        except Exception:
            log.debug("settings window: could not jump to a section", exc_info=True)

    def _render(sections: list[Section]) -> None:
        for child in body.winfo_children():
            child.destroy()
        for child in strip.winfo_children():
            child.destroy()
        for section in sections:
            header = tk.Label(body, text=f"[ {section.title} ]", bg=theme.BG,
                              fg=theme.RED, font=theme.mono(11, bold=True),
                              justify="left", anchor="w")
            header.pack(anchor="w", pady=(14, 2))
            theme.neon_button(
                tk, strip, section.title,
                (lambda header=header: _jump_to(header)), primary=False,
            ).pack(side="left", padx=(0, 8))
            tk.Label(body, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM,
                     font=theme.mono(9)).pack(anchor="w")
            for item in section.items:
                if isinstance(item, Line):
                    fg = {"muted": theme.MUTED, "warning": theme.RED}.get(item.style, theme.TEXT)
                    tk.Label(body, text=item.text, bg=theme.BG, fg=fg, font=theme.mono(10),
                             justify="left", anchor="w", wraplength=660
                             ).pack(anchor="w", pady=(2, 0))
                elif isinstance(item, Button):
                    theme.neon_button(
                        tk, body, item.label, _run(item.label, item.on_click),
                    ).pack(anchor="w", pady=(4, 0))

    refresh_job: list = [None]
    rendered: list = [None, 0.0]   # [signature, monotonic time of last render]

    def _signature(sections: list[Section]):
        """What the window LOOKS like, as a comparable value. Rebuilding
        every _REFRESH_MS destroyed and repacked every widget, and the bare
        frame between the two painted as a white flash on all the
        clickables, twice a second of every second (Alex, 2026-08-31)."""
        return tuple(
            (s.title,
             tuple((i.text, i.style) if isinstance(i, Line)
                   else ("btn", i.label) for i in s.items))
            for s in sections)

    def _refresh() -> None:
        if state["closed"]:
            return
        try:
            snap = tray_mod._tray_snapshot(app)
            sections = build_settings_model(snap, app)
            sig = _signature(sections)
            now = time.monotonic()
            # Skip the rebuild when nothing visible changed -- but never for
            # more than 30 s: a Button's on_click is bound to snapshot-derived
            # arguments at build time, and a handler must not act on a
            # snapshot older than that even when its label never moved.
            if sig != rendered[0] or now - rendered[1] > 30.0:
                keep = canvas.yview()[0] if rendered[0] is not None else None
                _render(sections)
                rendered[0], rendered[1] = sig, now
                if keep:
                    root.after_idle(lambda y=keep: canvas.yview_moveto(y))
        except Exception:
            log.exception("settings window: refresh failed")
        refresh_job[0] = root.after(_REFRESH_MS, _refresh)

    _refresh()
    try:
        from . import ui_dispatch

        ui_dispatch.run_dialog(root)
    finally:
        _release_and_close()
