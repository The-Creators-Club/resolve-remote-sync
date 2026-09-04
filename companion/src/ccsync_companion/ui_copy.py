"""Where the buttons are: the ONE place a route into the UI is spelled.

UX-1 / APP-2 / CYT-4 / CMEDIA-5 (usability sweep 2026-09-03, built
2026-09-04). The 2026-08-27 menu reduction (CR-88) cut the right-click menu
to ten rows and moved COPY DIAGNOSTICS FOR YOUR ADMIN, OPEN LOG, SCAN WHOLE
PROJECT, the YouTube items and the whole Advanced submenu into the Settings
window. About twenty editor-facing sentences kept pointing at the old rows,
and the fix pass that chased them wrote the new path out by hand at every
site - which is the same failure one menu move later.

So a route is a constant here and nowhere else. tests/test_sweep_2026_09_04_copy.py
fails on any other module writing "Tray >" into a user-visible string, and
tests/test_tray_copy_names_real_menu_items.py checks each route below still
ends at a row that exists (ROUTE_ROWS is the evidence it uses).

Punctuation: ">" for a navigation path, never "->" and never an arrow
glyph, because half the copy said one and half the other. No em dashes -
this is user-visible text (owner's rule, 2026-08-18).
"""
from __future__ import annotations

from typing import Any

# The tray's own rows (the ten-item menu in tray._build_menu).
QUIT = "Tray > Quit CCSync"
SIGN_IN = "Tray > Sign in"
SETTINGS = "Tray > Settings"
# In the menu only while the licence gate is up, which is the only time
# anything points at it.
ACCEPT_LICENCE = "Tray > Accept the licence agreement"

# [ HELP ] in the Settings window. The label is quoted in CAPS because that
# is exactly what is painted on the button (settings_window.build_settings_model).
DIAGNOSTICS = "Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN"
OPEN_LOG = "Tray > Settings > OPEN LOG"

# [ THIS COMPUTER ]. The tray keeps a Sign in row of its own while nobody is
# signed in; this is the one an editor whose token was REJECTED needs, and
# that advisory line is rendered inside the Settings window anyway.
SIGN_IN_SETTINGS = "Tray > Settings > SIGN IN"

# [ ADVANCED ].
SCAN_WHOLE_PROJECT = "Tray > Settings > SCAN WHOLE PROJECT"
CONSOLIDATE = ("Tray > Settings > BRING AN EXISTING PROJECT'S MEDIA INTO THE "
               "SYNCED FOLDER")
UNDO_RELINK = "Tray > Settings > UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE"
STOP_ALL_SYNCING = "Tray > Settings > STOP ALL SYNCING ON THIS COMPUTER"

# [ YOUTUBE ]. Sentence case, again because that is what the buttons say.
YOUTUBE_TERMS = "Tray > Settings > Accept YouTube Terms"
YOUTUBE_SIGN_IN = "Tray > Settings > Sign in to YouTube"
YOUTUBE_COOKIES = "Tray > Settings > Use an exported cookies.txt"

# The two rows whose label carries a value. Functions, not constants: a
# caller that has the name should say it, and one that does not gets the
# placeholder rather than a route that reads as if a project were called
# "<project>" by accident.
_REMOVE_PREFIX = "Tray > Settings > REMOVE "
_REPAIR_PREFIX = "Tray > Settings > REPAIR "


def remove_project(name: str = "") -> str:
    """"Tray > Settings > REMOVE 'FF5' FROM THIS COMPUTER"."""
    label = str(name or "").strip() or "<project>"
    return f"{_REMOVE_PREFIX}'{label}' FROM THIS COMPUTER"


def finish_grading(letter: str) -> str:
    """"Tray > Settings > FINISH GRADING: P: BACK TO LOCAL PROXIES" - the row
    that undoes a grade swap. It moved out of the right-click menu on
    2026-08-27, so "swap back from this menu" named nothing (SYNC-103)."""
    return f"Tray > Settings > FINISH GRADING: {letter} BACK TO LOCAL PROXIES"


def repair_drive(letter: str) -> str:
    """"Tray > Settings > REPAIR P: NOW" - the letter is site data, so the
    caller passes app.canonical_prefix_label() (COMMERCIAL_READINESS 11)."""
    return f"{_REPAIR_PREFIX}{letter} NOW"


# -- the one help page (SYS-21 / UX-3, sweep 2026-09-03) --------------------
#
# Nothing in the companion, the dashboard or any SPA linked to a single
# document explaining how the product works: the copy said "see EDITOR_SETUP
# step 6" (a file no editor has), "ask your admin" or nothing at all. The
# dashboard serves the deployed HOW_IT_WORKS.md at this path, and every
# surface that offers help builds its URL from THESE two, so the day it moves
# is one edit here.
HELP_URL_PATH = "/help"

# What the Settings window's row is called, for the copy that points at it.
HELP_PAGE = "Tray > Settings > HELP"


def help_url(cfg: Any = None) -> Any:
    """`<dashboard_url>/help`, or None on a computer with no dashboard yet.

    None rather than a relative path or a guess: a help link that 404s or
    lands on the wrong host is worse than a button that is not offered, and
    an unconfigured companion is exactly the machine whose editor would click
    it first."""
    try:
        base = str((cfg or {}).get("dashboard_url", "") or "").strip()
    except Exception:
        return None
    base = base.rstrip("/")
    if not base:
        return None
    return f"{base}{HELP_URL_PATH}"


# The row each route ends at, as that row's own source spells it. The test
# looks for these in tray.py and settings_window.py: a menu move that leaves
# the copy behind has to delete one of these labels to happen at all.
ROUTE_ROWS: dict[str, str] = {
    QUIT: "Quit CCSync",
    ACCEPT_LICENCE: "Accept the licence agreement",
    SIGN_IN_SETTINGS: "SIGN IN",
    SIGN_IN: "Sign in",
    SETTINGS: "Settings",
    DIAGNOSTICS: "COPY DIAGNOSTICS FOR YOUR ADMIN",
    OPEN_LOG: "OPEN LOG",
    SCAN_WHOLE_PROJECT: "SCAN WHOLE PROJECT",
    CONSOLIDATE: "BRING AN EXISTING PROJECT'S MEDIA INTO THE SYNCED FOLDER",
    UNDO_RELINK: "UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE",
    STOP_ALL_SYNCING: "STOP ALL SYNCING ON THIS COMPUTER",
    YOUTUBE_TERMS: "Accept YouTube Terms",
    YOUTUBE_SIGN_IN: "Sign in to YouTube",
    YOUTUBE_COOKIES: "Use an exported cookies.txt",
    remove_project(): "REMOVE '",
    repair_drive("P:"): "REPAIR ",
    finish_grading("P:"): "FINISH GRADING: ",
    # The Settings section itself (SYS-21): "Settings > Help > Copy
    # diagnostics" is the one route the sweep asked every surface to use, so
    # the section it names is checked like every other row.
    HELP_PAGE: "HELP",
}

# Every literal route this module publishes, for the scan test.
ROUTES: tuple[str, ...] = tuple(ROUTE_ROWS)


# -- the words for a lane, and for a count (UX-10, sweep 2026-09-04) --------
#
# The dashboard has said "upload" / "proxy download" / "folder sync" since it
# had lanes (dashboard health.py `_LANE_WORDS`); the companion said "Lane A".
# One person compares the two screens, so the tray reads the same words. The
# map is duplicated rather than imported because the companion ships without
# the dashboard package; the dashboard's copy is the one the API speaks.
LANE_WORDS = {
    "A": "upload",
    "lane_a_video_up": "upload",
    "B": "proxy download",
    "lane_b_proxy_down": "proxy download",
    "C": "folder sync",
    "lane_c_syncthing": "folder sync",
    "express": "express upload",
}


def lane_words(lane: Any, default: str = "syncing") -> str:
    """"upload" for lane A. A lane nobody has a word for gets `default`,
    never its letter: "Lane A stopped" is a sentence about our internals."""
    return LANE_WORDS.get(str(lane or "").strip(), default)


def count(number: Any, singular: str, plural: str = "") -> str:
    """"1 file" / "3 files" - a real plural, not "3 file(s)".

    The parenthetical plural is developer shorthand that leaked into about
    forty sentences an editor reads. Falls back to `singular + "s"`, which
    covers every noun this product counts (file, clip, folder, project, LUT,
    minute); pass `plural` for anything it does not."""
    try:
        n = int(number)
    except (TypeError, ValueError):
        n = 0
    word = singular if n == 1 else (plural or singular + "s")
    return f"{n} {word}"
