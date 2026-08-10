"""Shared fixtures."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pytest

COMPANION_ROOT = Path(__file__).resolve().parent.parent

# The one directory the test suite must never read from or write to.
REAL_CCSYNC_HOME = Path.home() / ".ccsync"


@pytest.fixture(autouse=True)
def _isolate_ccsync_home(tmp_path, monkeypatch):
    """Point EVERYTHING that resolves under ~/.ccsync at a per-test temp dir.

    Two separate reasons, both observed live:

    1. Tests constructing a CompanionApp otherwise load whatever
       identity.json the developer's own live companion has -- a signed-in
       role="base" identity flips _sync_enabled at construction, so
       test_role failed only on that machine and only while signed in.
       (2026-07-25.)

    2. Anything that calls setup_logging() -- directly, or via app.run()'s
       fallback for an unusable log_path -- opened a RotatingFileHandler on
       the real ~/.ccsync/companion.log and interleaved test output
       (tracebacks, G:\\raw\\A001.braw fixtures, "no display name and no
       $DISPLAY") into the live companion's log. That file is the one
       artifact the docs tell editors to send to their admin, so corrupting
       it actively costs support time. (2026-07-25.)

    HOME/USERPROFILE are redirected too, so even a literal "~/..." string
    that slips past the patched DEFAULTS cannot expanduser() its way back to
    the real directory.
    """
    from ccsync_companion import config as config_mod

    # A SIBLING of tmp_path, not a child: several tests assert on the exact
    # contents of tmp_path (e.g. "the failed download left nothing behind").
    fake_home = tmp_path.parent / f"{tmp_path.name}-home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".ccsync")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / ".ccsync" / "config.toml")
    # DEFAULTS["log_path"] is deliberately left as the literal
    # "~/.ccsync/companion.log" -- test_config asserts load_config returns
    # DEFAULTS verbatim. The env redirection above is what makes that literal
    # expanduser() into the fake home instead of the real one, which is the
    # property the guard test at the bottom of this file checks.

    yield

    # Close any file handler a test attached, so the temp dir can be removed
    # and no handle survives into the next test. "pystray" as well as
    # "ccsync": setup_logging() attaches the same handlers to both (the tray
    # backend's own records had nowhere to go in the windowed build), and a
    # handler left on that logger would keep writing into a deleted tmp dir
    # for the rest of the session.
    for logger_name in ("ccsync", "pystray"):
        logger = logging.getLogger(logger_name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


@pytest.fixture(autouse=True)
def _no_real_tk_windows(monkeypatch, request):
    """GUARD. No test may create a real Tk window.

    "Headless-safe" is not the same as "safe": the developer's Windows box
    HAS a display, so a dialog a test forgot to inject a fake for really
    opens, really sits on top of everything, and really blocks its daemon
    thread until someone clicks it. The one that existed
    (test_app.py's report-response fan-out, which let CompanionApp build a
    ProjectSetupPrompter with the default popup.confirm_dialog) popped the
    exact "NEW PROJECT — Project 'New Doc' isn't set up on the server"
    dialog the suite was written to prevent, and got mistaken for the live
    bug for a day (2026-07-25).

    Any attempt raises -- most of this package catches everything and
    degrades to the no-display path, so the exception alone would be
    invisible -- AND is recorded, so the test that caused it fails loudly
    here even if the production code swallowed it.
    """
    import tkinter

    attempts: list[str] = []

    def _blocked(name):
        def _raise(*args, **kwargs):
            attempts.append(name)
            raise RuntimeError(
                f"tkinter.{name}() in a test -- inject a fake dialog instead "
                "(see conftest._no_real_tk_windows)"
            )
        return _raise

    monkeypatch.setattr(tkinter, "Tk", _blocked("Tk"))
    monkeypatch.setattr(tkinter, "Toplevel", _blocked("Toplevel"))

    yield

    if attempts:
        pytest.fail(
            f"{request.node.name} tried to open {len(attempts)} real Tk "
            f"window(s) ({', '.join(sorted(set(attempts)))}) -- on a machine "
            "with a display that dialog appears on the user's desktop. "
            "Inject a fake confirm/popup callable."
        )


@pytest.fixture(autouse=True)
def _single_instance_slot_is_free(monkeypatch):
    """Pretend no other companion holds the single-instance slot.

    The guard is a NAMED WINDOWS MUTEX (app.acquire_single_instance), so it
    is global to the login session -- unlike ~/.ccsync, no tmp_path or HOME
    redirection can isolate a test from it. When a real companion is running
    on the developer's own machine, run() returns before constructing the
    app and any test asserting on construction order fails, with a symptom
    ("'construct' is not in list") that names nothing to do with the cause.

    Observed 2026-07-25: the suite was green all afternoon *because* the
    companion happened to be stopped, and went red the moment the fixed
    build was installed and launched -- i.e. the test outcome depended on
    the developer's desktop state, which is the same defect class as the
    live-log and real-Tk-window guards above.

    Tests that exercise the blocked path patch this to False themselves;
    a test-level monkeypatch applies after this fixture and wins.
    """
    from ccsync_companion import app as app_mod

    monkeypatch.setattr(app_mod, "acquire_single_instance", lambda: True)
    yield


@pytest.fixture(autouse=True)
def _fresh_resolve_bridge_session():
    """Start every test with a bridge that has never connected.

    resolve_bridge records "has the Resolve bridge connected THIS SESSION?"
    in module state (the tray and Copy diagnostics read it -- items 17/19),
    and a process is one session, so without this a test that enumerates a
    fake Resolve leaves every later test's tray snapshot carrying a
    `Resolve: connected` line it never asked for. Same class of hazard as
    _single_instance_slot_is_free above: process-global, so no tmp_path or
    HOME redirection can isolate it.

    Same for the watcher's poll cache (the fingerprint-gated skip of the
    per-clip walk): it is module state keyed on a fake timeline's shape, and
    two tests building the same fake would otherwise share an answer.
    """
    from ccsync_companion import resolve_bridge

    resolve_bridge.reset_session_state()
    resolve_bridge.reset_timeline_cache()
    yield
    resolve_bridge.reset_session_state()
    resolve_bridge.reset_timeline_cache()


@pytest.fixture
def darwin(monkeypatch):
    """Fake a macOS host.

    Patches the global `sys` module, which every module that reads
    `sys.platform` shares -- including ui_dispatch.platform_mode(), which
    reads it live at call time rather than caching a constant.
    """
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")


@pytest.fixture
def windows(monkeypatch):
    """Fake a Windows host, COMPLETELY.

    Faking sys.platform alone is not enough: it sends code into win32
    branches that then touch attributes only present in Windows' stdlib.
    upgrade.UpgradeManager._default_spawn is the worked example -- it reads
    subprocess.DETACHED_PROCESS, which does not exist on macOS, so the test
    died with AttributeError instead of exercising the branch (MAC-2a, first
    real macOS run 2026-08-04). Supplying the constants makes the fake
    self-consistent, so these tests genuinely cover the Windows path from any
    host rather than skipping.

    The values are the real Win32 ones; nothing here executes them.
    """
    import subprocess
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    for name, value in (
        ("DETACHED_PROCESS", 0x00000008),
        ("CREATE_NEW_PROCESS_GROUP", 0x00000200),
        ("CREATE_NO_WINDOW", 0x08000000),
        ("CREATE_NEW_CONSOLE", 0x00000010),
    ):
        if not hasattr(subprocess, name):
            monkeypatch.setattr(subprocess, name, value, raising=False)


def _rclone_candidates() -> list[Path]:
    """Every place a usable rclone might sit, in priority order after PATH.

    The old version of this looked ONLY at `.tools/rclone.exe`, which cannot
    exist on a Mac for two independent reasons: the name is wrong (the binary
    is `rclone`, no extension) and `.tools/` is gitignored, so a fresh clone
    has no such directory at all. The result was 24 lane-direction tests
    skipping silently on every Mac -- the tests that prove lane A carries
    video UP only and lane B carries **/Proxy/** DOWN only, which is the most
    destructive thing in the system to get backwards (found on the first real
    macOS run, 2026-08-04).

    So we also consult the path the INSTALLER actually uses. The companion's
    rclone is deliberately kept off PATH -- that is what the `rclone_path`
    config key and the INST-7 comment in the generated config.toml are about
    (launchd hands a LaunchAgent PATH=/usr/bin:/bin:/usr/sbin:/sbin) -- so a
    correctly-installed machine is precisely the one where `which` fails.
    """
    exe = "rclone.exe" if os.name == "nt" else "rclone"
    # Test-only portable copy, developer machines (see README's "Tests").
    candidates = [COMPANION_ROOT / ".tools" / exe]
    if os.name == "nt":
        # windows_bootstrap.ps1's BinDir. Only meaningful on Windows: with no
        # LOCALAPPDATA the fallback would name ~/ccsync/bin, which is nothing.
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.append(Path(local_appdata) / "ccsync" / "bin" / exe)
    else:
        # macos_bootstrap.sh's BIN_DIR.
        candidates.append(Path.home() / ".local" / "ccsync" / "bin" / exe)
    return candidates


def _find_rclone() -> str | None:
    """Look for a runnable rclone: PATH first, then _rclone_candidates()."""
    found = shutil.which("rclone")
    if found:
        return found
    for candidate in _rclone_candidates():
        if candidate.exists():
            return str(candidate)
    return None


def write_project_marker(project_dir, slug: str = "test-slug") -> None:
    """Stamp a directory as a project (.ccsync-project marker) -- since
    2026-07-25 discovery is marker-based, so tests that build project trees
    call this instead of relying on depth."""
    import json

    Path(project_dir).mkdir(parents=True, exist_ok=True)
    (Path(project_dir) / ".ccsync-project").write_text(
        json.dumps({"slug": slug}), encoding="utf-8"
    )


@pytest.fixture(scope="session")
def rclone_binary() -> str:
    """A real rclone to shell out to, or a skip -- unless the caller insists.

    Set CCSYNC_REQUIRE_RCLONE=1 to turn the skip into a hard failure. Both
    release scripts do, because pytest exits 0 when tests skip: 24 skipped
    lane-direction tests otherwise read as a green suite and authorise a
    build whose real-rclone coverage never ran.
    """
    path = _find_rclone()
    if path is not None:
        return path

    searched = "\n  ".join(["PATH"] + [str(c) for c in _rclone_candidates()])
    message = f"rclone not found. Searched:\n  {searched}"
    if os.environ.get("CCSYNC_REQUIRE_RCLONE") == "1":
        pytest.fail(
            f"{message}\n\nCCSYNC_REQUIRE_RCLONE=1 is set, so this is a failure "
            "rather than a skip -- these tests invoke a real rclone to prove the "
            "lane A/B filter directions, and a release must not be cut without them."
        )
    pytest.skip(message)


def make_timeline_item(
    file_path: str,
    clip_name: str | None = None,
    track_type: str = "video",
    track_index: int = 1,
    item_index: int = 0,
    media_pool_item=None,
) -> dict:
    """Build a fake resolve_bridge.get_timeline_items()-style item dict."""

    class _FakeMediaPoolItem:
        def __init__(self, path: str, name: str):
            self._path = path
            self._name = name
            self.replace_calls: list[str] = []
            self.replace_result = True

        def GetClipProperty(self):
            return {"File Path": self._path}

        def GetName(self):
            return self._name

        def ReplaceClip(self, new_path: str):
            self.replace_calls.append(new_path)
            return self.replace_result

    mpi = media_pool_item if media_pool_item is not None else _FakeMediaPoolItem(
        file_path, clip_name or Path(file_path).name
    )
    return {
        "file_path": file_path,
        "media_pool_item": mpi,
        "clip_name": clip_name or Path(file_path).name,
        "track_type": track_type,
        "track_index": track_index,
        "item_index": item_index,
    }


def _writes_under(path: Path, root: Path) -> bool:
    try:
        return path.resolve() == root.resolve() or root.resolve() in path.resolve().parents
    except OSError:
        return False


def test_no_test_can_resolve_to_the_real_ccsync_home(tmp_path):
    """GUARD. The suite must never touch ~/.ccsync -- not config.toml, not
    identity.json, and above all not companion.log, which is the artifact
    every doc tells editors to send to their admin when something breaks.

    Lives in conftest.py deliberately: it asserts the property that the
    autouse fixture above is responsible for, so it fails right next to the
    thing that would have to be wrong.
    """
    from ccsync_companion import config as config_mod

    resolved = config_mod.resolved_log_path({})
    assert not _writes_under(resolved, REAL_CCSYNC_HOME), (
        f"a default-config log path resolved to {resolved}, inside the REAL "
        f"{REAL_CCSYNC_HOME}"
    )
    assert not _writes_under(config_mod.CONFIG_PATH, REAL_CCSYNC_HOME)
    assert not _writes_under(config_mod.CONFIG_DIR, REAL_CCSYNC_HOME)

    # ...and the fallback path app.run() uses when log_path itself is broken.
    assert not _writes_under(
        Path(config_mod.DEFAULTS["log_path"]).expanduser(), REAL_CCSYNC_HOME
    )

    from ccsync_companion.identity import identity_path

    assert not _writes_under(identity_path(), REAL_CCSYNC_HOME)


def test_setup_logging_fallback_never_writes_to_the_real_home(tmp_path):
    """The specific regression: app._fallback_logging() falls back to
    DEFAULTS["log_path"], which is the literal "~/.ccsync/companion.log".
    Any test exercising a bad log_path therefore appended to the live log."""
    from ccsync_companion import app as app_mod

    app_mod._fallback_logging({"log_path": 5})
    handlers = logging.getLogger("ccsync").handlers
    for handler in handlers:
        filename = getattr(handler, "baseFilename", None)
        if filename:
            assert not _writes_under(Path(filename), REAL_CCSYNC_HOME), (
                f"logging fell back onto the live log at {filename}"
            )
