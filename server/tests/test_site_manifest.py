"""site.toml, blank defaults, and picking a backend (WP0 step 4 / WP3).

The contract these tests hold:

  - identity comes from ONE file, with flags and env vars still winning;
  - an unconfigured checkout REFUSES and names the key it wanted, instead of
    quietly aiming at 192.168.0.102 / /mnt/tank/TheCreatorsPool (that default
    was the reason a second deployment would have been a fork --
    docs/COMMERCIAL_READINESS.md item 10);
  - picking a backend opens nothing: every script builds one at startup, and a
    --dry-run is supposed to touch nothing at all. (Until 2026-08-17 this said
    "--nas-kind synology fails fast for as long as that backend is a stub" --
    it is implemented now, so what is left to hold is the free construction.)

Reloading `common` with a cleared environment is how the unconfigured state is
reached: the constants are computed at import, because they are argparse
defaults (see common.site_path_from_argv). Each test that does it restores the
module afterwards, so the rest of the suite keeps the fixture site.
"""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402

FIXTURE_SITE = Path(__file__).resolve().parent / "fixtures" / "site.toml"
EXAMPLE_SITE = Path(__file__).resolve().parents[2] / "site.example.toml"


@pytest.fixture
def unconfigured(monkeypatch):
    """`common`, re-imported with no site manifest and no TRUENAS_* env --
    i.e. a fresh checkout on someone else's machine."""
    # An EMPTY manifest, not an absent one: a real <repo>/site.toml exists on
    # any machine that ships (tools\ship.cmd requires it since 2026-08-17), and
    # reload() re-derives every DEFAULT_* at import time from whatever
    # load_site() finds -- so "unconfigured" must be pinned explicitly.
    monkeypatch.setenv(common.SITE_ENV_VAR,
                       str(Path(__file__).resolve().parent / "fixtures" / "empty-site.toml"))
    for name in ("TRUENAS_HOST", "TRUENAS_USER", "TRUENAS_PW", "CCSYNC_NAS_KIND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    fresh = importlib.reload(common)
    fresh.REPO_ROOT = Path(__file__).resolve().parent / "fixtures" / "no-site"
    fresh.load_site(reload=True)
    fresh.DEFAULT_TRUENAS_HOST = fresh.site_value("nas", "host")
    fresh.DEFAULT_DATASET_ROOT = fresh.site_value("tree", "pool_root")
    try:
        yield fresh
    finally:
        # Put the real module back for everything that runs after this file.
        monkeypatch.undo()
        importlib.reload(common)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def test_the_fixture_site_is_what_the_suite_runs_against():
    """conftest.py points $CCSYNC_SITE here before common is imported."""
    assert Path(common.site_file()) == FIXTURE_SITE
    assert common.DEFAULT_TRUENAS_HOST == "192.168.0.102"
    assert common.DEFAULT_CC_ROOT == "/mnt/tank/TheCreatorsPool/Creators_Club"
    assert common.DEFAULT_PROJECTS_ROOT.endswith("/Creators_Club/Projects")
    assert common.DEFAULT_APPS_ROOT == "/mnt/tank/apps/ccsync-dashboard"
    assert common.DEFAULT_HOMES_PARENT == "/mnt/tank/TheCreatorsPool/homes"


def test_the_example_manifest_parses_and_documents_every_section():
    site = common.load_site(EXAMPLE_SITE, reload=True)
    try:
        assert set(site) >= {"nas", "tree", "apps", "net", "syncthing", "stack"}
        assert site["nas"]["kind"] in common.NAS_KINDS
        text = EXAMPLE_SITE.read_text(encoding="utf-8")
        # The one rule about this file that is not a matter of taste.
        for secret in ("TRUENAS_PW", "SYNCTHING_API_KEY", "DASH_SESSION_SECRET"):
            assert secret in text, f"the example must say where {secret} lives"
        assert "NO SECRETS IN HERE" in text
        for section in ("[nas]", "[tree]", "[apps]", "[net]", "[syncthing]", "[stack]"):
            assert f"\n{section}\n" in text
    finally:
        common.load_site(FIXTURE_SITE, reload=True)


def test_a_named_but_missing_manifest_is_an_error(tmp_path):
    with pytest.raises(common.EnvError):
        common.load_site(tmp_path / "nope.toml", reload=True)
    common.load_site(FIXTURE_SITE, reload=True)


def test_the_site_path_is_read_straight_off_the_command_line():
    """--site has to be honoured before argparse exists: the constants are
    argparse DEFAULTS, and a parser bakes those in when it is built."""
    assert common.site_path_from_argv(["--site", "/x/site.toml"]) == "/x/site.toml"
    assert common.site_path_from_argv(["--site=/x/site.toml"]) == "/x/site.toml"
    assert common.site_path_from_argv(["--dry-run"]) == ""


# --------------------------------------------------------------------------
# Refusing, rather than pointing at somebody else's NAS
# --------------------------------------------------------------------------

def test_an_unconfigured_checkout_has_no_identity_defaults(unconfigured):
    for value in (unconfigured.DEFAULT_TRUENAS_HOST, unconfigured.DEFAULT_TRUENAS_USER,
                  unconfigured.DEFAULT_DATASET_ROOT, unconfigured.DEFAULT_CC_ROOT,
                  unconfigured.DEFAULT_PROJECTS_ROOT,
                  unconfigured.DEFAULT_BROLL_ARCHIVE_ROOT,
                  unconfigured.DEFAULT_HOMES_PARENT, unconfigured.DEFAULT_APPS_ROOT):
        assert value == "", value


def test_a_derived_root_is_blank_rather_than_a_wrong_absolute_path(unconfigured):
    """The trap this avoids: "" + "/Projects" is "/Projects" -- an absolute
    path, on the NAS's root filesystem, that mkdir -p and chown -R would
    happily accept."""
    assert not unconfigured.DEFAULT_PROJECTS_ROOT.startswith("/")
    assert not unconfigured.DEFAULT_BROLL_ARCHIVE_ROOT.startswith("/")


def test_the_refusal_names_the_key_and_the_flag(unconfigured):
    with pytest.raises(unconfigured.EnvError) as excinfo:
        unconfigured.require_site_value("", "[tree] pool_root", "--projects-root")
    message = str(excinfo.value)
    assert "[tree] pool_root" in message and "--projects-root" in message
    assert "site.example.toml" in message
    assert "192.168.0.102" not in message and "TheCreatorsPool" not in message


def test_connection_params_refuse_instead_of_defaulting(unconfigured):
    with pytest.raises(unconfigured.EnvError) as excinfo:
        unconfigured.truenas_conn_params(dry_run=True)
    assert "[nas] host" in str(excinfo.value)


def test_env_vars_still_win_over_the_manifest(unconfigured, monkeypatch):
    """The scripts' documented env vars keep working -- unchanged precedence,
    only the bottom of the chain moved."""
    monkeypatch.setenv("TRUENAS_HOST", "10.0.0.9")
    monkeypatch.setenv("TRUENAS_USER", "someone")
    host, user, pw = unconfigured.truenas_conn_params(dry_run=True)
    assert (host, user) == ("10.0.0.9", "someone")
    assert pw.startswith("<TRUENAS_PW")


def test_cli_turns_a_configuration_refusal_into_one_line(capsys):
    def main():
        raise common.EnvError("[tree] pool_root is not configured. Set it in ...")

    assert common.cli(main) == 2
    err = capsys.readouterr().err
    assert err.startswith("FAILED: [tree] pool_root is not configured")
    assert "Traceback" not in err


# --------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------

def test_the_default_backend_is_truenas():
    backend = common.get_backend()
    assert backend.kind == "truenas"
    assert backend.host_root_re.match("/mnt/tank/apps/ccsync-dashboard")
    # ix-<app_name>-<service>-1, and the app_name here IS "ccsync-dashboard" --
    # so the doubled word is the real container name on this NAS, not a typo.
    assert backend.dashboard_container == "ix-ccsync-dashboard-dashboard-1"


def test_the_kind_comes_from_the_flag_then_the_env_then_the_site(monkeypatch):
    class Args:
        nas_kind = "synology"

    monkeypatch.delenv(common.NAS_KIND_ENV, raising=False)
    assert common.nas_kind(Args()) == "synology"
    monkeypatch.setenv(common.NAS_KIND_ENV, "synology")
    assert common.nas_kind(None) == "synology"
    monkeypatch.delenv(common.NAS_KIND_ENV)
    assert common.nas_kind(None) == "truenas"      # [nas] kind in the fixture


def test_an_unknown_kind_is_refused(monkeypatch):
    monkeypatch.setenv(common.NAS_KIND_ENV, "qnap")
    with pytest.raises(common.EnvError):
        common.nas_kind(None)


def test_selecting_synology_opens_nothing_at_construction(monkeypatch):
    """The backend is real since 2026-08-17 (it was a refusing stub before),
    but get_backend() must still be free: every script builds one at startup,
    including on a --dry-run that is supposed to touch nothing."""
    monkeypatch.setenv(common.NAS_KIND_ENV, "synology")
    monkeypatch.setattr(common, "truenas_api",
                        lambda *a, **k: pytest.fail("get_backend must touch no network"))
    monkeypatch.setattr(common, "synology_api",
                        lambda *a, **k: pytest.fail("get_backend must touch no network"))
    monkeypatch.setattr(common, "run_ssh",
                        lambda *a, **k: pytest.fail("get_backend must open no SSH session"))
    backend = common.get_backend()
    assert backend.kind == "synology" and backend.ready is True


def test_the_synology_backend_carries_its_shape():
    """The deploy-target regex is a REFUSAL, so it is correct from day one:
    the install REPLACES everything under <host-root>/app as root."""
    from backends.synology import SynologyBackend  # noqa: PLC0415

    backend = SynologyBackend()
    assert backend.kind == "synology" and backend.ready is True
    assert backend.host_root_re.match("/volume1/docker/ccsync")
    assert backend.host_root_re.match("/volume2/apps/ccsync/data")
    for bad in ("/mnt/tank/apps/ccsync-dashboard", "/volume1/ccsync", "/volumeX/d/ccsync",
                "/", "/volume1/docker/ccsyncx"):
        assert not backend.host_root_re.match(bad), bad
    assert backend.dashboard_container == "ccsync-dashboard-1"


def test_the_synology_backend_answers_every_method_the_protocol_names():
    """The Synology half of the same list the TrueNAS test below checks --
    which was this port's to-do list while the backend was a stub."""
    from backends import base  # noqa: PLC0415
    from backends.synology import SynologyBackend  # noqa: PLC0415

    backend = SynologyBackend()
    for name in dir(base.ServerBackend):
        if name.startswith("_"):
            continue
        assert hasattr(backend, name), f"SynologyBackend is missing {name}"


def test_the_truenas_backend_answers_every_method_the_protocol_names():
    """Not a Protocol isinstance check (those only look at names): this is the
    list the scripts call, and the Synology agent's to-do list."""
    from backends import base  # noqa: PLC0415

    backend = common.get_backend()
    for name in dir(base.ServerBackend):
        if name.startswith("_"):
            continue
        assert hasattr(backend, name), f"TrueNASBackend is missing {name}"


def test_the_steps_truenas_does_not_automate_say_so_rather_than_pretending():
    """ensure_share / ensure_service_user / snapshot are UI steps here (the
    pool layout is a one-time decision made with recordsize and ACL settings no
    script should guess). They must not silently return success."""
    from backends.base import UnsupportedOnBackend  # noqa: PLC0415

    backend = common.get_backend()
    with pytest.raises(UnsupportedOnBackend):
        backend.ensure_share("tree", "/mnt/tank/x", "editors", dry_run=True)
    with pytest.raises(UnsupportedOnBackend):
        backend.ensure_service_user("broll", "editors", dry_run=True)
    with pytest.raises(UnsupportedOnBackend):
        backend.snapshot("/mnt/tank/x", "pre-deploy", dry_run=True)
    # ...while the one that is genuinely a no-op here is a no-op, not a raise:
    # an account with a shell and a home IS an SFTP account on TrueNAS.
    assert backend.grant_sftp("editors", dry_run=True) is True
