"""Bug hunt 2026-09-11, install-onboard territory (CR-248).

Three of the six findings live in onboarding/steps.py:

- install-onboard-1: the macOS "installer is on a mounted volume" guard walked
  up from the exe and refused at the first os.path.ismount() hit. On macOS
  10.15+ that is /Users itself (APFS volume group: the writable Data volume is
  reached through firmlinks, so its st_dev differs from /'s), so every frozen
  wizard run from Downloads, the Desktop or /Applications was refused, with no
  place left to copy it to. The old darwin tests all injected is_mount, which
  is precisely the thing that was wrong, so the suite could not see it: the
  tests here drive the DEFAULT with the firmlink st_dev shape simulated.
- install-onboard-2: run_bootstrap read canonical_prefix / tree_name off the
  passed dict only, so a failed manifest fetch (site=None) handed the
  bootstrap nothing while ensure_config resolved the same keys from the CACHE.
- install-onboard-5: an explicit port that was not 443 forced http://, and
  Tailscale Serve/Funnel publishes TLS on 8443 here.

Nothing here may depend on the developer's own ~/.ccsync or on the real
filesystem: every site value and every stat is passed or simulated.
"""

from __future__ import annotations

import os
import posixpath
import stat as stat_mod

import pytest

import steps
from ccsync_companion import site as site_mod


# -- install-onboard-1: the APFS Data volume is not a foreign mount ------------

# Arbitrary device numbers; only their equality matters. The shape is every
# macOS 10.15+ machine's: / is the sealed System volume, everything a person
# can write is the Data volume, and the two have different st_dev values.
_DEV_SYSTEM = 16777220
_DEV_DATA = 16777221
_DEV_EXTERNAL = 16777230


class _FakeStat:
    def __init__(self, dev: int, ino: int = 0) -> None:
        self.st_dev = dev
        self.st_ino = ino
        self.st_mode = 0o040755  # a directory, never a symlink


def _firmlink_stat(path, *args, **kwargs) -> _FakeStat:
    p = posixpath.normpath(str(path))
    # st_ino is per-path and stable: posixpath.ismount falls back to it when
    # a path and its parent share a device, and the pre-fix mechanism this
    # file has to be able to run is posixpath.ismount (tests-1, 2026-09-11b).
    ino = abs(hash(p)) % (2 ** 31) or 1
    if p.startswith("/Volumes/") or p.startswith("/mnt/"):
        return _FakeStat(_DEV_EXTERNAL, ino)
    for firmlinked in ("/System/Volumes/Data", "/Users", "/Applications"):
        if p == firmlinked or p.startswith(firmlinked + "/"):
            return _FakeStat(_DEV_DATA, ino)
    return _FakeStat(_DEV_SYSTEM, ino)


def _old_guard_verdict(exe: str) -> bool:
    """The pre-fix darwin branch, verbatim from 40f931a: walk up from the exe
    and refuse at the first mount point. Kept here (tests-1, 2026-09-11b)
    because the shipped guard no longer contains the mechanism the shipped
    bug was, and a regression test that cannot state the bug cannot fail on
    it."""
    if exe.startswith("/Volumes/"):
        return True
    path = posixpath.dirname(exe)
    while path and path != "/":
        if posixpath.ismount(path):
            return True
        parent = posixpath.dirname(path)
        if parent == path:
            break
        path = parent
    return False


def _guard_under_firmlinks(monkeypatch, exe, probe=None, pre_fix_is_mount=True):
    """Run the REAL guard (no injected callable) against a simulated
    volume-group Mac.

    os.stat is swapped for the shortest possible window and put back in a
    finally: pytest's own collection, caching and traceback formatting all
    stat real files, so a fixture-wide patch takes the test session down
    rather than the test.

    tests-1 (2026-09-11b): `_default_is_mount` is substituted with posixpath's
    ismount as well. The pre-fix guard reached the mount table through
    `os.path.ismount`, and on the Windows dev box and the Windows CI job --
    THE ONLY RUNNERS THIS SUITE HAS -- os.path is ntpath, whose ismount never
    reads st_dev and answers False for every POSIX path. The old code was
    therefore green against this whole file, and these tests could not fail on
    the bug they were written for. The new guard does not call
    `_default_is_mount` at all, so the substitution changes nothing about what
    is under test; it only puts the macOS semantics back under the mechanism
    a revert would restore.
    """
    monkeypatch.setattr(steps.sys, "frozen", True, raising=False)
    monkeypatch.setattr(steps.sys, "executable", exe)
    monkeypatch.setenv("HOME", "/Users/leso")
    if pre_fix_is_mount:
        monkeypatch.setattr(steps, "_default_is_mount",
                            lambda path: posixpath.ismount(path))
    real_stat, real_lstat = os.stat, os.lstat
    os.stat = _firmlink_stat
    os.lstat = _firmlink_stat
    try:
        verdict = steps.installer_on_forbidden_drive(platform="darwin")
        probed = probe() if probe is not None else None
    finally:
        os.stat = real_stat
        os.lstat = real_lstat
    return verdict, probed


def test_the_simulation_really_is_a_mount_boundary(monkeypatch):
    """If this stops being true the rest of the file proves nothing: the old
    guard's refusal came from ismount("/Users") being True."""
    verdict, ismount_users = _guard_under_firmlinks(
        monkeypatch, "/Users/leso/Desktop/onboard",
        probe=lambda: posixpath.ismount("/Users"))
    assert ismount_users is True
    assert stat_mod.S_ISDIR(_firmlink_stat("/Users").st_mode)
    assert verdict is False


def test_the_pre_fix_walk_refuses_what_the_shipped_guard_allows(monkeypatch):
    """tests-1 (2026-09-11b): the two answers must DIFFER under the same
    simulation. Without this, a revert of the darwin branch is green
    everywhere the suite runs."""
    exe = "/Users/leso/Desktop/onboard"
    verdict, old = _guard_under_firmlinks(
        monkeypatch, exe, probe=lambda: _old_guard_verdict(exe))
    assert old is True, "the simulation no longer reproduces the shipped bug"
    assert verdict is False


@pytest.mark.skipif(
    os.path is not posixpath,
    reason="os.path is ntpath on this runner and ntpath.ismount never reads "
           "st_dev, so the unpatched pre-fix mechanism answers False for every "
           "POSIX path here. SAID OUT LOUD rather than passing (tests-1): the "
           "rest of the file substitutes posixpath.ismount for "
           "steps._default_is_mount so the mechanism is exercised anyway. "
           "This suite runs on Windows only -- see the OWED note in "
           "docs/bug-hunt-2026-09-11b/ledger/install-onboard.md about adding "
           "onboarding to the macOS CI job.")
def test_the_shipped_default_is_mount_is_the_pre_fix_mechanism(monkeypatch):
    """On a POSIX runner, the module's own `_default_is_mount` is the thing
    that used to refuse the home folder."""
    _verdict, probed = _guard_under_firmlinks(
        monkeypatch, "/Users/leso/Desktop/onboard",
        probe=lambda: steps._default_is_mount("/Users"),
        pre_fix_is_mount=False)
    assert probed is True


@pytest.mark.parametrize("exe", [
    "/Users/leso/Downloads/CCSync Onboarding.app/Contents/MacOS/onboard",
    "/Users/leso/Desktop/onboard",
    "/Applications/CCSync Onboarding.app/Contents/MacOS/onboard",
])
def test_the_home_folder_and_applications_are_fine(monkeypatch, exe):
    assert _guard_under_firmlinks(monkeypatch, exe)[0] is False


def test_a_volumes_path_is_still_refused(monkeypatch):
    exe = ("/Volumes/TheCreatorsPool/Assets/Software/onboard.app"
           "/Contents/MacOS/onboard")
    assert _guard_under_firmlinks(monkeypatch, exe)[0] is True


def test_an_external_volume_outside_volumes_is_refused(monkeypatch):
    # An SSD mounted somewhere else: a different device from both halves of
    # the boot volume group and from the home folder.
    assert _guard_under_firmlinks(monkeypatch, "/mnt/t7/software/onboard")[0] is True


def test_a_stat_that_raises_never_refuses(monkeypatch):
    monkeypatch.setattr(steps.sys, "frozen", True, raising=False)
    monkeypatch.setattr(steps.sys, "executable", "/Users/leso/Desktop/onboard")

    def boom(path):
        raise OSError("statfs hung on a dead automount")

    assert steps.installer_on_forbidden_drive(
        platform="darwin", stat_dev=boom) is False


def test_the_refusal_wording_is_the_platforms_own():
    mac = steps.forbidden_installer_message("P", platform="darwin")
    assert "onboard.exe" not in mac
    assert "drive" not in mac.lower()
    assert "/Volumes" in mac
    assert "\u2014" not in mac
    win = steps.forbidden_installer_message("Q", platform="win32")
    assert "Q:" in win and "onboard.exe" in win
    assert "\u2014" not in win


# -- install-onboard-2: the cached manifest reaches the bootstrap --------------

Q_CACHE = {"canonical_prefix": "Q:\\", "tree_name": "Pool"}


class _FakeResult:
    returncode = 0
    stdout = ""
    stderr = ""


def _capture_run(calls):
    def run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs.get("env") or {})))
        return _FakeResult()
    return run


def _script(tmp_path, name):
    p = tmp_path / name
    p.write_text("# stand-in", encoding="utf-8")
    return str(p)


def test_windows_bootstrap_gets_the_cached_prefix_after_a_failed_fetch(
        tmp_path, monkeypatch):
    monkeypatch.setattr(site_mod, "cached_site", lambda **kw: dict(Q_CACHE))
    calls = []
    steps.run_bootstrap(
        editor_name="jane", dashboard_token="t", tailnet_host="nas",
        dashboard_url="http://nas:8480", site=None, platform="win32",
        script_path=_script(tmp_path, "windows_bootstrap.ps1"),
        run=_capture_run(calls))
    cmd = calls[0][0]
    assert "-CanonicalPrefix" in cmd and cmd[cmd.index("-CanonicalPrefix") + 1] == "Q:\\"
    assert "-TreeName" in cmd and cmd[cmd.index("-TreeName") + 1] == "Pool"


def test_macos_bootstrap_gets_the_cached_prefix_after_a_failed_fetch(
        tmp_path, monkeypatch):
    monkeypatch.setattr(site_mod, "cached_site", lambda **kw: dict(Q_CACHE))
    calls = []
    steps.run_bootstrap(
        editor_name="jane", dashboard_token="t", tailnet_host="nas",
        dashboard_url="http://nas:8480", site=None, platform="darwin",
        script_path=_script(tmp_path, "macos_bootstrap.sh"),
        run=_capture_run(calls))
    env = calls[0][1]
    assert env.get("CCSYNC_CANONICAL_PREFIX") == "Q:\\"
    assert env.get("CCSYNC_TREE_NAME") == "Pool"


def test_no_cache_means_the_script_fetches_for_itself(tmp_path, monkeypatch):
    """The wizard's own P:\\ default must NEVER reach the bootstrap: an env
    var or a flag carrying it would beat the script's fetch, which is
    install-onboard-2 pointing the other way."""
    monkeypatch.setattr(site_mod, "cached_site", lambda **kw: {})
    calls = []
    steps.run_bootstrap(
        editor_name="jane", dashboard_token="t", tailnet_host="nas",
        dashboard_url="http://nas:8480", site=None, platform="win32",
        script_path=_script(tmp_path, "windows_bootstrap.ps1"),
        run=_capture_run(calls))
    assert "-CanonicalPrefix" not in calls[0][0]
    assert "-TreeName" not in calls[0][0]

    calls = []
    steps.run_bootstrap(
        editor_name="jane", dashboard_token="t", tailnet_host="nas",
        dashboard_url="http://nas:8480", site=None, platform="darwin",
        script_path=_script(tmp_path, "macos_bootstrap.sh"),
        run=_capture_run(calls))
    assert "CCSYNC_CANONICAL_PREFIX" not in calls[0][1]
    assert "CCSYNC_TREE_NAME" not in calls[0][1]


def test_a_fetched_manifest_still_beats_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(site_mod, "cached_site", lambda **kw: dict(Q_CACHE))
    calls = []
    steps.run_bootstrap(
        editor_name="jane", dashboard_token="t", tailnet_host="nas",
        dashboard_url="http://nas:8480",
        site={"canonical_prefix": "R:\\", "tree_name": "Fresh"},
        platform="win32",
        script_path=_script(tmp_path, "windows_bootstrap.ps1"),
        run=_capture_run(calls))
    cmd = calls[0][0]
    assert cmd[cmd.index("-CanonicalPrefix") + 1] == "R:\\"
    assert cmd[cmd.index("-TreeName") + 1] == "Fresh"


def test_an_unreadable_cache_is_not_fatal(tmp_path, monkeypatch):
    def boom(**kw):
        raise OSError("~/.ccsync is not readable")

    monkeypatch.setattr(site_mod, "cached_site", boom)
    calls = []
    code, _out = steps.run_bootstrap(
        editor_name="jane", dashboard_token="t", tailnet_host="nas",
        dashboard_url="http://nas:8480", site=None, platform="win32",
        script_path=_script(tmp_path, "windows_bootstrap.ps1"),
        run=_capture_run(calls))
    assert code == 0
    assert "-CanonicalPrefix" not in calls[0][0]


# -- install-onboard-5: a TLS port is not an http port -------------------------

@pytest.mark.parametrize("typed,expected", [
    # Tailscale Serve publishes the dashboard on 443 and the client-share
    # port 8443, both TLS. Guessing http:// for 8443 wrote an unusable URL
    # into the field, config.toml and the companion's loopback allow-list.
    ("nas.tail26290e.ts.net:8443", "https://nas.tail26290e.ts.net:8443"),
    # install-onboard-5 (2026-09-11b): 8443 is this deployment's Funnel
    # port, and a customer's own 8443 is as often the plain container port.
    ("dash.example.com:8443", "http://dash.example.com:8443"),
    # A tailnet name is https on any port: Serve terminates TLS for all of them.
    ("nas.tail26290e.ts.net:8480", "https://nas.tail26290e.ts.net:8480"),
    # Unchanged: a bare container port on someone's own deployment, and every
    # numeric or local address, has no certificate on it.
    ("dash.example.com:8480", "http://dash.example.com:8480"),
    ("192.168.0.104:8443", "http://192.168.0.104:8443"),
    ("localhost:8443", "http://localhost:8443"),
])
def test_normalise_dashboard_url_does_not_force_http_on_a_tls_port(typed, expected):
    assert steps.normalise_dashboard_url(typed) == expected


def test_a_typed_scheme_is_never_second_guessed():
    for url in ("http://nas.tail26290e.ts.net:8443", "https://dash.example.com:8480"):
        assert steps.normalise_dashboard_url(url) == url
