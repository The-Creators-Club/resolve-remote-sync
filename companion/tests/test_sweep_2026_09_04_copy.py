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
import re
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
    # ...and it says COMPUTER since the wave 4 vocabulary (2026-09-04).
    assert ui_copy.remove_project("FF5") == (
        "Tray > Settings > REMOVE 'FF5' FROM THIS COMPUTER")
    assert ui_copy.remove_project() == (
        "Tray > Settings > REMOVE '<project>' FROM THIS COMPUTER")
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


# -- wave 4: ONE VOCABULARY (sweep 2026-09-03 section 4) ---------------------
#
# The owner approved one word per concept on 2026-09-04, because the same
# thing had four names across the tray, the Settings window and the dashboard
# and an editor on the phone to their admin was reading a different word for
# it on each screen:
#
#   * a computer is a COMPUTER in copy ("machine" stays in code, routes and
#     DB columns; "device" is a Syncthing identity and nothing else);
#   * sync that is not running is PAUSED (you did it), STOPPED BY YOUR ADMIN
#     (a fleet halt) or STOPPED ITSELF (the breaker, the disk floor);
#   * the transports are UPLOAD / PROXY DOWNLOAD / FOLDER SYNC, never a lane
#     and never a letter;
#   * a project is TICKED, the set of them is a SYNC PLAN.
#
# So: a scan for the retired words over the modules whose copy this pass
# converted. The list is the point of the test - a module joins MODULES when
# its strings have been read, never by loosening what counts.

RETIRED_WORDS: tuple[str, ...] = (
    "lane", "lane a", "lane b", "lane c", "machine", "base rig", "rig",
    "halted", "parked", "breaker", "selection", "assignment",
)

# The modules converted on 2026-09-04. A partial list that FAILS is worth more
# than a complete one that is allowed to pass, so a module joins this tuple
# when its strings have been READ - never by loosening what counts.
MODULES: tuple[str, ...] = (
    "tray.py", "tray_native.py", "app.py", "ui_copy.py", "jobs_runner.py",
    "capabilities.py", "drive_reminder.py", "eula.py", "sync/lane_guard.py",
    # ...and the Settings window, whose own suite carries the same scan over
    # the model it builds (test_settings_window.py). Both, deliberately: this
    # one reads the literals, that one reads the rendered rows.
    "settings_window.py",
    # Wave 5, same day: the loopback server's ~15 ingest refusals and their
    # music siblings (every one of them a sentence in the b-roll or music web
    # UI's own toast, because the page prints the companion's `message`
    # verbatim), the on-demand clip fetch, both ingestors, and the two windows
    # an editor watches a fix or an index run in.
    "broll_server.py", "music_server.py", "broll_fetch.py", "broll_ingest.py",
    "music_ingest.py", "popup.py", "fixer.py", "sync/rclone_lane.py",
    # ...and the two sidecars, whose refusals are RAISED into the same
    # capability answers and the same toasts: "no usable GPU on this machine"
    # reached an editor through broll_server's `reasons` list, so converting
    # the caller and not the callee would have left the page saying both
    # words in one sentence.
    "broll_vlm_sidecar.py", "music_clap_sidecar.py",
)

# Where the word is not the concept. Each entry is the EXACT string, and each
# one is here for a reason that is about that string, never about the effort
# of changing it.
VOCABULARY_ALLOWED: dict[str, str] = {
    # A report reason code on the wire (app._report_off_cycle), read by the
    # dashboard's log and by nobody else. Not copy.
    "lane B resumed": "an internal report reason, never rendered",
    # Two `self.log` lines in the ingestors. The scan subtracts the arguments
    # of a module-level `log.…` call and cannot see a logger held on an
    # instance, so these two reach it as if they were sentences; they are
    # diagnostics, and the house rule exempts log lines deliberately (a scan
    # that failed on one is a scan people learn to work around - the same
    # reason test_the_sentences_ux10_named_no_longer_say_lane_a_or_s reads
    # two named files rather than the package).
    "kept %d staged file(s) the base rig still has to finish: %s":
        "a self.log.info line in broll_ingest, not copy",
    "%s stays on this machine for the base rig - %s":
        "a self.log.warning line in music_ingest, not copy",
}

_WORD_RE = re.compile(r"\b(" + "|".join(RETIRED_WORDS) + r")\b", re.IGNORECASE)


def _key_string_nodes(tree: ast.AST) -> set[int]:
    """String literals that are DICT KEYS or lookups, not sentences.

    `guard.get("parked")`, `{"reason": ...}`, `snap["machine"]`: state keys
    are the vocabulary of the wire and the state files, which deliberately
    did not change (CLAUDE.md: code identifiers, routes and DB columns keep
    their names)."""
    keys: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(id(key))
        elif isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                keys.add(id(node.slice))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("get", "pop", "setdefault", "startswith",
                                  "endswith", "count", "split", "rsplit",
                                  "strip", "lstrip", "rstrip", "index", "find"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        keys.add(id(arg))
    return keys


def _sentences(path: Path) -> list[str]:
    """The visible strings of `path` that are PROSE.

    Three or more words: a one- or two-word literal is a state code, a JSON
    key, an ffmpeg flag or a menu glyph, and the sweep's finding is about
    sentences an editor reads."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = (_docstring_nodes(tree) | _log_argument_nodes(tree)
            | _key_string_nodes(tree))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip:
            continue
        if len(node.value.split()) < 3:
            continue
        out.append(node.value)
    return out


@pytest.mark.parametrize("name", MODULES)
def test_no_retired_word_in_a_sentence_an_editor_reads(name: str) -> None:
    bad = []
    for text in _sentences(SRC / name):
        if text in VOCABULARY_ALLOWED:
            continue
        found = _WORD_RE.findall(text)
        if found:
            bad.append((sorted(set(w.lower() for w in found)), text))
    assert not bad, (
        f"{name} says a retired word to an editor: {bad}. The vocabulary "
        f"(sweep 2026-09-03 section 4, owner-approved 2026-09-04): a computer "
        f"is a 'computer'; sync is 'paused' (you), 'stopped by your admin' (a "
        f"fleet halt) or 'stopped itself' (the breaker or the disk floor); the "
        f"transports are 'upload' / 'proxy download' / 'folder sync'. If the "
        f"word is genuinely not the concept, add the exact string to "
        f"VOCABULARY_ALLOWED with the reason.")


def test_the_vocabulary_scan_would_catch_a_regression() -> None:
    """...and that its two exemptions do not swallow a real sentence."""
    from tempfile import NamedTemporaryFile

    src = (
        'ok = "Syncing is stopped on this computer"\n'
        'bad = "Syncing is halted on this machine"\n'
        'key = snap.get("machine")\n'
        'code = "lane B resumed"\n'
    )
    with NamedTemporaryFile("w", suffix=".py", delete=False,
                            encoding="utf-8") as handle:
        handle.write(src)
        path = Path(handle.name)
    try:
        found = [t for t in _sentences(path)
                 if _WORD_RE.search(t) and t not in VOCABULARY_ALLOWED]
    finally:
        path.unlink(missing_ok=True)
    assert found == ["Syncing is halted on this machine"], found


def test_the_allow_list_has_a_reason_for_every_entry() -> None:
    for text, why in VOCABULARY_ALLOWED.items():
        assert text and why.strip(), text
        assert _WORD_RE.search(text), (
            f"{text!r} is exempted from a scan that would not have flagged it")


# -- UX-19: a stop and a pause are two switches with one word ---------------
#
# With both set the menu carried "Start syncing again" and "Resume syncing
# (currently PAUSED)" four lines apart, and clicking either left the computer
# not syncing with nothing on screen saying there were two.

def test_the_local_stop_is_named_for_its_cause_and_dated() -> None:
    from ccsync_companion.tray import halt_release_label

    label = halt_release_label({"halt": {"active": True, "scope": "local",
                                         "at": "2026-09-04T09:12:00+00:00"}})
    assert label.startswith("► Clear the sync stop on this computer (set ")
    assert label.endswith(")")
    # A stamp nothing can read drops the parenthetical rather than dating the
    # stop to now (CR-89's rule).
    assert halt_release_label({"halt": {"active": True, "at": "nonsense"}}) == (
        "► Clear the sync stop on this computer")
    assert halt_release_label({}) == "► Clear the sync stop on this computer"


def test_two_switches_are_named_as_two() -> None:
    from ccsync_companion.tray import _sync_line, _two_stops_line

    both = {"sync_guard": {"halt": {"active": True, "scope": "local"}},
            "paused": True, "statuses": []}
    assert _two_stops_line(both) == (
        "⚠ Two things are stopping sync on this computer: a stop and a pause. "
        "Clear both to sync again.")
    assert "and paused" in _sync_line(both)

    fleet = {"sync_guard": {"halt": {"active": True, "scope": "fleet"}},
             "paused": True, "statuses": []}
    assert "your admin's stop and a pause" in _two_stops_line(fleet)

    # One switch is one sentence, and the line is the higher-ranked one -
    # the same order the dashboard's health.why_not_syncing uses.
    assert _two_stops_line({"sync_guard": {"halt": {"active": True}},
                            "paused": False}) is None
    assert _two_stops_line({"paused": True}) is None


# -- SYS-21 (a): one help page, one constant --------------------------------

def test_the_help_page_has_one_url_and_one_route() -> None:
    from ccsync_companion import ui_copy

    assert ui_copy.HELP_URL_PATH == "/help"
    assert ui_copy.help_url({"dashboard_url": "https://nas.example.ts.net/"}) == (
        "https://nas.example.ts.net/help")
    assert ui_copy.help_url({"dashboard_url": "https://nas.example.ts.net"}) == (
        "https://nas.example.ts.net/help")
    # None, never a relative path or a guess: a help link that lands on the
    # wrong host is worse than a button that is not offered, and a computer
    # with no dashboard yet is exactly the one whose editor would click it.
    assert ui_copy.help_url({}) is None
    assert ui_copy.help_url(None) is None
    assert ui_copy.help_url({"dashboard_url": "   "}) is None
