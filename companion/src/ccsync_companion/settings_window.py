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
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from . import config as config_mod
from . import tray as tray_mod
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
                "NOTHING to it: no uploads, no proxy downloads, no shared "
                "project files. Your admin will not be able to tick projects "
                "for it either. If this laptop keeps its own copy of the "
                "projects, this is not the setting you want."
            )
            confirmed = popup.confirm_dialog(
                "CCSYNC.EXE: switch to WIRED TO THE SERVER", body,
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
                "drive. If this machine's synced folder is actually the "
                "live server share (the base rig), switching will start "
                "DELETING files from it the moment a proxy-download pass "
                "runs, because that lane syncs the server DOWN onto "
                "whatever this machine calls its own copy.\n\n"
                "If you are not sure this machine has its own separate "
                "copy of the project tree, do not do this.\n\n"
                'Type "REMOTE" to confirm:'
            )
            confirmed = tray_mod._ask_typed_confirmation_locked(
                app, "CCSYNC.EXE: switch to REMOTE EDITOR", body, "REMOTE",
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
            tray_mod._notify(app, "CCSync could not repair the drive mapping. Tray > "
                                  "Settings > COPY DIAGNOSTICS FOR YOUR ADMIN.")
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
            tray_mod._notify(app, "CCSync could not undo that. Tray > Settings > COPY "
                                  "DIAGNOSTICS FOR YOUR ADMIN.")
            return
        if forgotten:
            tray_mod._notify(app, f"CCSync will offer clips in {folder} again.")
        else:
            # "Could not check" must never render as "done": the entry was
            # already gone, and saying so is cheaper than a second click.
            tray_mod._notify(app, f"{folder} was not on the leave-alone list.")
    tray_mod._spawn(app, "Forget folder ignore", _do)


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


def build_settings_model(snap: dict, app: "CompanionApp") -> list[Section]:
    """Pure: snapshot + app -> the sections the window renders. No tkinter."""
    sections: list[Section] = []

    # -- [ THIS COMPUTER ] ---------------------------------------------------
    current_role = app.effective_mode() if hasattr(app, "effective_mode") else "editor"
    computer_items: list = [
        Line(f"Machine name: {platform.node()}"),
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
        computer_items.append(Button("RESTART CCSYNC NOW", lambda: action_restart_now(app)))
    computer_items.append(Line(str(snap.get("identity_label", ""))))
    if snap.get("signed_in"):
        computer_items.append(Button("SIGN OUT", lambda: tray_mod.action_sign_out(app)))
    else:
        computer_items.append(Button("SIGN IN…", lambda: tray_mod.action_sign_in(app)))
    sections.append(Section("THIS COMPUTER", computer_items))

    # -- [ SYNC LANES ] -------------------------------------------------------
    lane_items: list = [
        Line(tray_mod._format_lane_line_from(
            s, paused=bool(snap.get("paused")), problems=bool(snap.get("problems")),
            root_absent=bool(snap.get("root_absent")),
        ))
        for s in snap.get("statuses", [])
    ]
    for text in (snap.get("sequencer_line"), snap.get("current_project_line")):
        if text:
            lane_items.append(Line(text))
    guard = snap.get("sync_guard") or {}
    for text in (tray_mod._halt_line(guard), tray_mod._breaker_line(guard),
                 tray_mod._skipped_exists_line(guard),
                 # SYNC-5 / UX-7 (resilience sweep 2026-08-28): both read the
                 # same sync_guard the four above do.
                 tray_mod._unfiltered_line(guard), tray_mod._conflicts_line(guard),
                 # APP-1 / APP-13 / APP-6 (resilience sweep 2026-08-28): the
                 # three states that used to be visible NOWHERE on the
                 # machine they were happening on. Above the trash line
                 # because each one is something that has stopped working.
                 tray_mod._reporter_line(guard), tray_mod._clock_skew_line(guard),
                 # APP-2 / UX-4 (same sweep): the clips the editor dismissed,
                 # which were visible in no artefact anybody ever sees.
                 tray_mod._ignored_line(guard),
                 tray_mod._crashes_line(guard),
                 # SYS-2 (same sweep): the watchdog restarting one thread over
                 # and over is a self-healing machine that still needs a human.
                 tray_mod._restarts_line(guard),
                 # REL-8 / APP-5 (same sweep): the update this computer has
                 # given up on, and the build it rolled itself back off.
                 tray_mod._upgrade_line(guard), tray_mod._reverted_line(guard),
                 # SYNC-1 (same sweep, CR-91): a wedged rclone the companion
                 # had to kill. The machine it happened ON said nothing at
                 # all about it before this line existed.
                 tray_mod._stalled_line(guard),
                 # SYS-5/SYNC-7 then SYNC-15 (same sweep): the free-space
                 # park, then the ONE ordered sentence the fleet grid shows
                 # for this machine -- last, because it summarises the rest.
                 tray_mod._disk_line(guard), tray_mod._blocked_line(guard),
                 tray_mod._trash_line(guard)):
        if text:
            lane_items.append(Line(text, style="warning"))
    if snap.get("root_unfinished"):
        # CR-92: the drive went out with work owed. The balloon says it
        # every half hour; this is where it stays readable in between.
        lane_items.append(Line(
            f"Your drive was disconnected with {snap['root_unfinished']} still to "
            f"go - plug it back in to finish syncing", style="warning"))
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
            "PROXIES THIS MACHINE HAS MADE…", lambda: tray_mod.action_proxy_history(app)))

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

    sections.append(Section("SYNC LANES", lane_items))

    # -- [ YOUTUBE ] ------------------------------------------------------
    if snap.get("ytdl_local_downloads") or snap.get("ytdl_youtube_signin"):
        yt_items: list = []
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

    # -- [ ADVANCED ] -------------------------------------------------------
    advanced_items: list = [
        Button("SCAN WHOLE PROJECT", lambda: tray_mod.action_scan_whole_project(app)),
        Button("BRING AN EXISTING PROJECT'S MEDIA INTO THE SYNCED FOLDER…",
               lambda: tray_mod.action_consolidate_project(app)),
        Button("UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE…",
               lambda: tray_mod.action_undo_last_relink(app)),
    ]
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
        advanced_items.append(Button(
            "FINISH GRADING: P: BACK TO LOCAL PROXIES"
            if snap.get("p_mode") == "server"
            else "GRADE FROM SERVER ORIGINALS (SWAP P:)…",
            lambda: tray_mod.action_grade_swap(app, snap),
        ))
    if not halt_active:
        advanced_items.append(Button(
            "STOP ALL SYNCING ON THIS MACHINE…", lambda: tray_mod.action_halt_sync(app)))
    for proj in snap.get("removable", []):
        slug = proj.get("slug", "")
        rel = proj.get("rel", "")
        label = (
            "REMOVE '" + rel.split("/")[-1] + "'"
            + (" (upload only)" if proj.get("upload_only") else "")
            + " FROM THIS MACHINE…"
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
    upgrade_info = snap.get("upgrade_info")
    if upgrade_info:
        help_items.append(Button(
            upgrade_mod.offer_label(upgrade_info["version"]),
            lambda: tray_mod.action_update_now(app)))
    help_items.append(Line(f"ccsync-companion v{config_mod.VERSION}", style="muted"))
    sections.append(Section("HELP", help_items))

    return sections


# -- the Tk shell -------------------------------------------------------

_WINDOW_TITLE = "CCSYNC.EXE: SETTINGS"
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

    root.title(_WINDOW_TITLE)
    theme.apply_window_icon(tk, root)
    root.configure(bg=theme.BG)
    root.geometry("720x640")
    root.minsize(560, 420)
    root.protocol("WM_DELETE_WINDOW", _release_and_close)
    root.bind("<Escape>", lambda _e: _release_and_close())

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

    def _render(sections: list[Section]) -> None:
        for child in body.winfo_children():
            child.destroy()
        for section in sections:
            tk.Label(body, text=f"[ {section.title} ]", bg=theme.BG, fg=theme.RED,
                     font=theme.mono(11, bold=True), justify="left", anchor="w"
                     ).pack(anchor="w", pady=(14, 2))
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

    def _refresh() -> None:
        if state["closed"]:
            return
        try:
            snap = tray_mod._tray_snapshot(app)
            _render(build_settings_model(snap, app))
        except Exception:
            log.exception("settings window: refresh failed")
        refresh_job[0] = root.after(_REFRESH_MS, _refresh)

    _refresh()
    try:
        from . import ui_dispatch

        ui_dispatch.run_dialog(root)
    finally:
        _release_and_close()
