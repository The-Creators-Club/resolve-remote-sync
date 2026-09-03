"""The wave 0 string day: the copy the 2026-09-03 sweep found, pinned.

`docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` section 5. Every assertion
here failed before the pass that added this file, and each one names its
finding id.

Two shapes:

  * a SCAN over the package's user-visible string literals (the same AST walk
    test_no_em_dash.py uses, with docstrings and log arguments subtracted),
    for the phrases that are retired: a navigation route written anywhere but
    ui_copy.py, a storage vendor's name, a hardcoded drive letter in a
    sentence, and the developer copy on the sequencer's line;
  * unit assertions on the functions that produce the rest, because a
    sentence about a misplaced drive is only wrong when the drive is
    misplaced.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from test_no_em_dash import _docstring_nodes, _log_argument_nodes, _py_files

SRC = Path(__file__).resolve().parents[1] / "src" / "ccsync_companion"


def _visible_strings(path: Path) -> list[str]:
    """Every string literal in `path` that an editor might read."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_nodes(tree) | _log_argument_nodes(tree)
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in skip]


# -- UX-1 / APP-2 / CYT-4 / CMEDIA-5: one module owns the routes -------------

@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_only_ui_copy_spells_a_menu_route(path: Path) -> None:
    """"Tray > ..." is written in ui_copy.py and interpolated everywhere else.

    The 2026-08-27 menu move left about twenty sentences pointing at rows
    that no longer existed; the pass that chased them wrote the new path out
    by hand at every site, which is the same failure one menu move later.
    """
    if path.name == "ui_copy.py":
        return
    bad = [s for s in _visible_strings(path)
           if "Tray >" in s or "tray >" in s or "Tray →" in s
           or "tray →" in s or "tray menu →" in s]
    assert not bad, (
        f"{path.name} writes a menu route into its own copy: {bad}. Import "
        f"`from . import ui_copy` and interpolate ui_copy.DIAGNOSTICS / "
        f"OPEN_LOG / SCAN_WHOLE_PROJECT / ... instead - that module is the "
        f"only place the next menu move has to be applied.")


def test_the_route_scan_would_catch_a_regression() -> None:
    src = "x = 'Something went wrong. Tray > Settings > OPEN LOG.'\n"
    tree = ast.parse(src)
    skip = _docstring_nodes(tree) | _log_argument_nodes(tree)
    found = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and id(n) not in skip and "Tray >" in n.value]
    assert found


def test_the_retired_routes_are_gone_from_every_module() -> None:
    """The exact sentences the sweep quoted, by their distinguishing half."""
    retired = (
        "Tray > Accept the licence agreement…",       # UX-1 (app.py)
        "tray > 'Accept YouTube Terms",                   # CYT-4
        "Sign in to YouTube again…)",                # CYT-4
        "see its log (Tray > Settings",                   # CMEDIA-5
        "Sign in again from this menu",                   # UX-1
        "Swap back from this menu",                       # SYNC-103
        "start them again from this menu",                # UX-1
        "later from the tray menu.",                      # UX-1
    )
    for path in _py_files():
        if path.name == "ui_copy.py":
            continue  # the live routes live there, in these very words
        text = path.read_text(encoding="utf-8")
        for phrase in retired:
            assert phrase not in text, f"{path.name} still says {phrase!r}"


def test_ui_copy_is_importable_without_the_package_starting() -> None:
    """It must be safe for every module to import: no companion imports, no
    I/O, nothing that a frozen build could fail at."""
    from ccsync_companion import ui_copy

    assert ui_copy.DIAGNOSTICS.startswith("Tray > Settings > ")
    assert ui_copy.remove_project("FF5") == (
        "Tray > Settings > REMOVE 'FF5' FROM THIS MACHINE")
    assert ui_copy.remove_project() == (
        "Tray > Settings > REMOVE '<project>' FROM THIS MACHINE")
    assert ui_copy.repair_drive("Q:") == "Tray > Settings > REPAIR Q: NOW"
    assert "Q:" in ui_copy.finish_grading("Q:")


def test_the_sentences_that_carry_a_route_carry_the_real_one() -> None:
    from ccsync_companion import loopback_guard, resolve_bridge, ui_copy, ytdl_executor

    assert ui_copy.OPEN_LOG in loopback_guard.REFUSED_MESSAGE
    assert ui_copy.QUIT in resolve_bridge.NO_SCRIPTING_MESSAGE
    assert ui_copy.YOUTUBE_TERMS in ytdl_executor.REASON_NOT_ATTESTED


# -- APP-10 / SYNC-114: no storage vendor in an editor's sentence ------------

@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_no_vendor_name_in_visible_copy(path: Path) -> None:
    # config.py is exempt, deliberately: its strings are the commented
    # config.toml template and the refusals that go with it, which name
    # /mnt/<pool> (TrueNAS) and /volume1 (Synology) as PATH SHAPES to an
    # admin filling the file in. That is documentation of two products'
    # layouts, not a sentence in a dialog an editor reads, and blanking it
    # would make the one file a human edits by hand less useful.
    if path.name == "config.py":
        return
    bad = [s for s in _visible_strings(path)
           if "TrueNAS" in s or "Synology" in s]
    assert not bad, (
        f"{path.name} names a storage vendor in copy an editor reads: {bad}. "
        f"The server's name is site data - site.server_phrase(), which falls "
        f"back to 'the server'.")


def test_server_phrase_is_named_by_the_manifest_and_neutral_otherwise(tmp_path) -> None:
    from ccsync_companion import site as site_mod

    assert site_mod.server_phrase(site={}) == "the server"
    assert site_mod.server_phrase(site={"org_short": "CCT"}) == "the CCT server"
    assert site_mod.server_phrase(site={"org_name": "Creators Club"}) == (
        "the Creators Club server")


# -- RES-9 / SYNC-103: the drive letter is site data -------------------------

def test_no_hardcoded_drive_letter_in_a_sentence() -> None:
    """The phrasings the sweep quoted. Not a general "P:" ban: drive_swap's
    default, a config key's default and a test fixture all legitimately say
    P:, and the letter itself is still what every machine in the field uses.
    """
    phrases = ("the P: drive", "P: swap failed", "SWAP P: TO SERVER",
               "SWAP P: BACK", "FINISH GRADING: P:", "Point P:",
               "REPAIR P: NOW")
    for path in _py_files():
        for text in _visible_strings(path):
            for phrase in phrases:
                assert phrase not in text, (
                    f"{path.name} hardcodes the sync drive letter in copy: "
                    f"{text!r}. Use app.canonical_prefix_label() (a sentence) "
                    f"or app.canonical_drive_letter() (a letter).")


# -- SYNC-104: the stall watchdog's own words, not "Something went wrong" ----

def test_a_killed_stalled_lane_reads_as_a_stall() -> None:
    from ccsync_companion.tray import classify_lane_error

    for raw in ("rclone made no progress for 900s - killed",
                "rclone did not exit after 30s - killed"):
        said = classify_lane_error(raw)
        assert "stopped moving" in said, said
        assert "Something went wrong" not in said


# -- SYNC-105: a misplaced drive is not a disconnected one -------------------

def test_a_misplaced_drive_is_never_called_disconnected() -> None:
    from ccsync_companion import root_guard
    from ccsync_companion.sync.base import STATE_ERROR, LaneStatus
    from ccsync_companion.tray import (
        _format_lane_line_from, _sync_line, _tooltip_text, classify_lane_error,
        drive_absent_phrase)

    assert drive_absent_phrase(root_guard.ROOT_MISPLACED) == (
        "the drive is mounted at the wrong place")
    assert drive_absent_phrase(root_guard.ROOT_NOT_ANSWERING) == (
        "the drive is not answering")
    assert drive_absent_phrase(root_guard.ROOT_ABSENT) == "drive disconnected"

    snap = {
        "root_absent": True, "root_state": root_guard.ROOT_MISPLACED,
        "problems": False, "paused": False, "signed_in": True,
        "sync_guard": {}, "root_unfinished": "",
    }
    assert "wrong place" in _sync_line(snap)
    assert "disconnected" not in _sync_line(snap)
    assert "wrong place" in _tooltip_text(snap)

    status = LaneStatus(name="lane_b")
    line = _format_lane_line_from(status, paused=False, problems=False,
                                  root_absent=True,
                                  root_state=root_guard.ROOT_MISPLACED)
    assert "wrong place" in line and "disconnected" not in line

    status = LaneStatus(name="lane_b")
    status.state = STATE_ERROR
    status.last_error = "some rclone noise"
    said = classify_lane_error(status.last_error, root_absent=True,
                               root_state=root_guard.ROOT_MISPLACED)
    assert "Plug it back in" not in said


def test_the_misplaced_sentence_does_not_prescribe_the_fault() -> None:
    """(b) of SYNC-105: `state_sentence` reaches the tray AND the dashboard,
    and "eject it and plug it back in" reproduces the fault."""
    from ccsync_companion import root_guard

    said = root_guard.state_sentence(root_guard.ROOT_MISPLACED)
    assert "leftover empty folder" in said
    assert said != "the sync drive is mounted at the wrong place - eject it and plug it back in"


# -- SYNC-116: the sequencer's most-read line, in words -----------------------

def test_no_selection_says_what_it_means() -> None:
    from ccsync_companion.sync.sequencer import Sequencer

    describe = Sequencer._describe_no_selection
    assert describe([], "dashboard") == (
        "Nothing to sync yet: no projects are ticked for this computer")
    assert describe(None, "cache").startswith("Waiting for the server")
    assert describe(None, "none") == (
        "Waiting for the server: this computer has no plan saved yet")
    for text in (describe([], "dashboard"), describe(None, "cache"),
                 describe(None, "none")):
        assert "no selection" not in text


# -- APP-3 / APP-4: a toast that is delivered, with its instruction ----------

def test_a_multiline_toast_is_one_line_for_applescript() -> None:
    from ccsync_companion.tray_native import _flatten_toast

    assert _flatten_toast("a\nb\tc\r\nd") == "a b c d"


def test_an_overlong_toast_keeps_its_last_sentence() -> None:
    from ccsync_companion.tray_native import TOAST_LIMIT, fit_toast

    head = "CCSync STOPPED downloading proxies as a safety measure: "
    middle = "the NAS root does not look like the tree, saw 0 entries. " * 6
    tail = "Your uploads are still running."
    fitted = fit_toast(head + middle + tail)
    assert len(fitted) <= TOAST_LIMIT
    assert fitted.endswith(tail), fitted
    assert fitted.startswith("CCSync STOPPED downloading")
    # Short messages are untouched, including their newlines (Windows shows
    # them; only the macOS backend flattens).
    assert fit_toast("all fine\nreally") == "all fine\nreally"


# -- UX-4: the title of every balloon and modal is the fleet's, not a build's -

# `ccsync-companion` is also the console script, the exe stem, the logger
# prefix and the single-instance mutex; only a TITLE is in scope. These are
# the two shapes the sweep counted: a title with a suffix after the colon,
# and the bare name passed where a title goes.
@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_no_build_artefact_names_a_dialog(path: Path) -> None:
    bad = [s for s in _visible_strings(path)
           if s.startswith("ccsync-companion: ") or s.startswith("CCSYNC.EXE")
           or s == "ccsync-companion"]
    assert not bad, (
        f"{path.name} titles something an editor reads with a package name or "
        f"a filename: {bad}. site.notify_title('...') is the title - the org's "
        f"short name from the manifest, the product's name otherwise.")


def test_notify_title_is_the_fleet_then_the_product(monkeypatch) -> None:
    from ccsync_companion import site as site_mod

    monkeypatch.setattr(site_mod, "org_short", lambda *a, **k: "Creators Club")
    assert site_mod.notify_title() == "Creators Club"
    assert site_mod.notify_title("licence agreement") == (
        "Creators Club: licence agreement")
    monkeypatch.setattr(site_mod, "org_short", lambda *a, **k: "")
    monkeypatch.setattr(site_mod, "product_name", lambda *a, **k: "CC Sync")
    assert site_mod.notify_title("update") == "CC Sync: update"


def test_the_title_is_read_when_it_is_shown_not_at_import(monkeypatch) -> None:
    """A module-level constant would be the name from before this machine
    ever fetched its site manifest."""
    from ccsync_companion import drive_reminder, settings_window
    from ccsync_companion import site as site_mod

    monkeypatch.setattr(site_mod, "org_short", lambda *a, **k: "Late Arrival")
    assert drive_reminder.notify_title() == "Late Arrival: sync unfinished"
    assert settings_window._window_title() == "Late Arrival: SETTINGS"


# -- UX-10: one vocabulary for a lane, and real plurals ----------------------

def test_a_stalled_lane_is_named_in_the_dashboard_s_words() -> None:
    from ccsync_companion import ui_copy

    assert ui_copy.lane_words("A") == "upload"
    assert ui_copy.lane_words("lane_b_proxy_down") == "proxy download"
    assert ui_copy.lane_words("C") == "folder sync"
    assert ui_copy.lane_words("express") == "express upload"
    # A lane nobody has a word for is never rendered as its letter.
    assert ui_copy.lane_words("Z") == "syncing"
    assert ui_copy.lane_words(None) == "syncing"


def test_counts_are_pluralised_properly() -> None:
    from ccsync_companion import ui_copy

    assert ui_copy.count(1, "file") == "1 file"
    assert ui_copy.count(3, "file") == "3 files"
    assert ui_copy.count(0, "project folder") == "0 project folders"
    assert ui_copy.count(2, "LUT") == "2 LUTs"
    assert ui_copy.count(1, "entry", "entries") == "1 entry"
    assert ui_copy.count(4, "entry", "entries") == "4 entries"
    assert ui_copy.count(None, "file") == "0 files"


def test_the_sentences_ux10_named_no_longer_say_lane_a_or_s() -> None:
    """The exact sentences the sweep quoted. Visible strings only: a log
    line counting "%d file(s)" is a diagnostic, not copy, and this file must
    not be the reason someone rewrites one."""
    retired = (
        "minute(s) and was restarted",
        "video file(s) have not been uploaded",
        "shared file(s) have not arrived",
        "project folder(s) put back",
        "finished staging folder(s), ",
        "project(s) are not sharing yet",
        "clip(s), ",                       # popup's preflight line
        "timeline clip(s) live outside",
        "file(s) in. Your originals",
    )
    # The two files the finding named. Deliberately not the whole package:
    # `self.log.info("%d clip(s)")` in broll_ingest is a log line that the
    # log-argument filter cannot see (it is `self.log`, not `log`), and a
    # scan that fails on it would be a scan people learn to work around.
    for name in ("app.py", "popup.py"):
        for text in _visible_strings(SRC / name):
            for phrase in retired:
                assert phrase not in text, (
                    f"{name} still says {phrase!r} to an editor: "
                    f"ui_copy.count(n, 'file') writes a real plural.")
    # ...and the lane's letter, which is a source shape rather than a phrase.
    assert 'f"Lane {stalled.get(' not in (SRC / "app.py").read_text(encoding="utf-8")
