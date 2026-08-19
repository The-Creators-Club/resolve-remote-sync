"""The YouTube feature is OFF unless the customer's site turned it on.

docs/COMMERCIAL_READINESS.md items 2 and 3 (2026-08-17), companion half.
docs/legal/YOUTUBE_FEATURE_NOTICE.md is the customer-facing statement of what
these two flags mean.

Three things are held to here, and the third is the one that is easy to get
wrong:

  - **`youtube_download` off = no surface at all.** No tray items, no loopback
    action, no tooling downloaded onto the disk.
  - **`youtube_unblock` is a SECOND, narrower flag.** deno (the n-challenge
    solver) and the browser-cookie sign-in exist only under it, because their
    only job is getting past YouTube's anti-automation measures.
  - **absence is OFF, not on.** No cached manifest, an old dashboard, an
    unreadable file -- all of them read as "this customer has not said yes".
    A client that cannot ask must never assume it may.
"""

from __future__ import annotations

import json

import pytest

from ccsync_companion import site as site_mod
from ccsync_companion import sidecar_tools, ytdl_attestation, ytdl_cookies
from ccsync_companion import ytdl_executor as ex
from ccsync_companion import ytdl_server, ytdlp_manager


@pytest.fixture(autouse=True)
def _read_the_real_flag(monkeypatch):
    """Undo conftest's "the site said yes" default for THIS module.

    conftest patches site.feature_enabled so the rest of the suite is not
    testing the switch; these tests ARE the switch, so they need the reader
    itself -- including its answer when there is no manifest at all.
    """
    monkeypatch.setattr(site_mod, 'feature_enabled',
                        site_mod._feature_enabled_unpatched)
    yield


def _site(download=False, unblock=False):
    site_mod.save_site({
        "schema": site_mod.SCHEMA,
        "features": {"youtube_download": download, "youtube_unblock": unblock},
    })


def _no_site():
    """An old dashboard, or a machine that has never reached one."""
    try:
        site_mod.site_path().unlink()
    except OSError:
        pass


# --------------------------------------------------------------- the manifest

def test_a_manifest_without_features_reads_as_every_feature_off():
    """A dashboard that predates the flags sends no `features` at all. The
    absence is a NO, and the whole point of the switch."""
    site = site_mod.normalise({"schema": 1, "org_name": "Someone"})
    # Every whitelisted flag, each one off -- spelled via FEATURE_KEYS so
    # adding a flag (CR-40: auto_update) does not need this test re-pinned.
    assert site["features"] == {key: False for key in site_mod.FEATURE_KEYS}
    assert set(site_mod.FEATURE_KEYS) >= {"youtube_download", "youtube_unblock", "auto_update"}
    for key in site_mod.FEATURE_KEYS:
        assert site_mod.feature_enabled(key, site) is False


@pytest.mark.parametrize("value", ["true", 1, "1", {}, [], "yes"])
def test_only_a_real_json_true_turns_a_feature_on(value):
    """A hand-edited cache, or a half-migrated dashboard, must not be able to
    assert that this customer may download YouTube material."""
    site = site_mod.normalise({"schema": 1, "features": {"youtube_download": value}})
    assert site["features"]["youtube_download"] is False


def test_no_cached_manifest_at_all_is_off_and_never_raises():
    _no_site()
    assert site_mod.feature_enabled("youtube_download") is False
    assert site_mod.feature_enabled("youtube_unblock") is False
    assert site_mod.feature_enabled("something-nobody-defined") is False


def test_an_unreadable_cache_is_off(monkeypatch):
    site_mod.site_path().parent.mkdir(parents=True, exist_ok=True)
    site_mod.site_path().write_text("{not json", encoding="utf-8")
    assert site_mod.feature_enabled("youtube_download") is False


def test_the_flags_survive_a_save_and_reload_round_trip():
    _site(download=True, unblock=True)
    cached = site_mod.cached_site()
    assert cached["features"]["youtube_download"] is True
    assert cached["features"]["youtube_unblock"] is True
    assert cached["features"]["auto_update"] is False   # not in _site(): stays off
    assert json.loads(site_mod.site_path().read_text(encoding="utf-8"))["features"]


# ------------------------------------------------------- youtube_download off

def test_the_site_flag_comes_before_the_editors_own_opt_out():
    """`ytdl_local_downloads` is one editor saying "not on my machine".
    `youtube_download` is the customer saying the feature exists at all, and it
    is asked first -- so a config.toml cannot switch a feature back on."""
    _site(download=False)
    assert ytdlp_manager.youtube_enabled({"ytdl_local_downloads": True}) is False
    _site(download=True)
    assert ytdlp_manager.youtube_enabled({"ytdl_local_downloads": True}) is True
    assert ytdlp_manager.youtube_enabled({"ytdl_local_downloads": False}) is False
    # ...and the config-only helper is untouched: it still answers its own
    # question, which is what the two-gate split is for.
    assert ytdlp_manager.local_downloads_enabled({"ytdl_local_downloads": True}) is True


def test_no_sidecar_tooling_is_downloaded_on_an_off_site(tmp_path):
    _site(download=False)

    def _must_not_run(*a, **kw):
        raise AssertionError("an off site downloaded a binary")

    out = sidecar_tools.ensure({}, github_open=_must_not_run)
    assert out["ok"] is False
    assert out["action"] == sidecar_tools.ACTION_DISABLED


def test_the_loopback_reveal_route_is_refused_on_an_off_site():
    """A feature that is off should have no surface at all -- and a page that
    can still make the companion open Explorer is surface."""
    _site(download=False)
    status, body = ytdl_server.build_reveal_response(
        {"rel_path": "2026/FF5/x/Youtube/t/clip.mp4"}, {"projects": "P:\\Projects"})
    assert status == 200 and body["ok"] is False
    assert "not enabled for this site" in body["message"]


def test_capabilities_says_off_rather_than_claiming_a_job(tmp_path):
    _site(download=False)
    deps = ex.Deps({"dashboard_url": "http://d", "dashboard_token": "t"},
                   editor_fn=lambda: "editor2",
                   identity_token_fn=lambda: "v2.identity.token")
    cap = ex.capabilities(deps)
    assert cap["ok"] is False
    assert cap["reason"] == ex.REASON_DISABLED


# -------------------------------------------------------- youtube_unblock off

def test_deno_is_not_installed_without_the_unblock_flag(tmp_path, monkeypatch):
    """deno's only job here is answering YouTube's JS challenge. The vendor
    build ships ffmpeg and no challenge solver."""
    _site(download=True, unblock=False)
    wanted = []
    monkeypatch.setattr(sidecar_tools, "is_installed", lambda tool="ffmpeg": False)
    monkeypatch.setattr(sidecar_tools, "_editor_has_own_ffmpeg", lambda *a: False)
    monkeypatch.setattr(sidecar_tools, "_editor_has_own_deno", lambda: False)
    monkeypatch.setattr(sidecar_tools, "ensure_tools_dir", lambda: tmp_path,
                        raising=False)
    monkeypatch.setattr(sidecar_tools.ytdlp_manager, "ensure_tools_dir",
                        lambda: tmp_path)
    monkeypatch.setattr(sidecar_tools, "_free_space_ok", lambda d: True)
    monkeypatch.setattr(sidecar_tools, "install_tool",
                        lambda tool, *a, **kw: wanted.append(tool) or True)

    sidecar_tools.ensure({})
    assert "deno" not in wanted
    assert set(wanted) == {"ffmpeg", "ffprobe"}

    wanted.clear()
    _site(download=True, unblock=True)
    sidecar_tools.ensure({})
    assert "deno" in wanted


def test_a_deno_already_on_disk_is_not_handed_to_yt_dlp_when_off(monkeypatch):
    """The switch has to stop yt-dlp being handed a challenge solver, not
    merely stop a download -- an editor upgraded from a build that installed
    one still has the binary."""
    monkeypatch.setattr(sidecar_tools, "is_installed", lambda tool="ffmpeg": True)
    _site(download=True, unblock=False)
    assert sidecar_tools.managed_deno() is None
    _site(download=True, unblock=True)
    assert sidecar_tools.managed_deno() is not None


def test_the_signed_in_cookies_are_refused_and_ignored_when_off(tmp_path):
    _site(download=True, unblock=False)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    assert ytdl_cookies.resolve({"ytdl_cookies_file": str(cookies)}) is None
    ok, message = ytdl_cookies.install(str(cookies), dest=tmp_path / "saved.txt")
    assert ok is False and message == ytdl_cookies.OFF_MESSAGE
    assert not (tmp_path / "saved.txt").exists()


# ------------------------------------------------------- the rights attestation

def test_nothing_downloads_until_the_terms_are_accepted_on_this_machine(tmp_path):
    _site(download=True, unblock=True)
    state = tmp_path / "attest.json"
    assert ytdl_attestation.accepted("editor2", state) is False

    ok, _msg = ytdl_attestation.accept("editor2", state)
    assert ok is True
    assert ytdl_attestation.accepted("editor2", state) is True
    # ...for THAT editor, on THIS machine. A shared workstation does not carry
    # one person's acceptance over to the next.
    assert ytdl_attestation.accepted("someone-else", state) is False
    assert ytdl_attestation.accepted("", state) is False


def test_a_re_worded_notice_re_prompts(tmp_path, monkeypatch):
    state = tmp_path / "attest.json"
    ytdl_attestation.accept("editor2", state)
    monkeypatch.setattr(ytdl_attestation, "TEXT_VERSION", "2099-01-01.1")
    assert ytdl_attestation.accepted("editor2", state) is False


def test_an_unreadable_or_absent_record_is_not_accepted(tmp_path):
    state = tmp_path / "attest.json"
    assert ytdl_attestation.accepted("editor2", state) is False
    state.write_text("{not json", encoding="utf-8")
    assert ytdl_attestation.accepted("editor2", state) is False
    state.write_text('["a list"]', encoding="utf-8")
    assert ytdl_attestation.accepted("editor2", state) is False


def test_accepting_records_who_when_and_which_wording(tmp_path):
    state = tmp_path / "attest.json"
    ytdl_attestation.accept("editor2", state)
    record = json.loads(state.read_text(encoding="utf-8"))
    assert record["accepted_by"] == "editor2"
    assert record["version"] == ytdl_attestation.TEXT_VERSION
    assert record["accepted_at"].startswith("20")


def test_nobody_signed_in_cannot_accept(tmp_path):
    ok, message = ytdl_attestation.accept("  ", tmp_path / "attest.json")
    assert ok is False and "sign in" in message
    assert not (tmp_path / "attest.json").exists()


def test_the_companion_text_is_pinned_to_the_servers_version():
    """The two halves of one notice. Editing the wording means bumping both, or
    the fleet's records point at text nobody agreed to."""
    server = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "ytdl" / "web" / "ytdlweb" / "attestation.py"
    )
    body = server.read_text(encoding="utf-8")
    assert f"TEXT_VERSION = '{ytdl_attestation.TEXT_VERSION}'" in body, (
        "companion/ytdl_attestation.TEXT_VERSION and ytdlweb/attestation.py "
        "have drifted -- bump both together")


def test_capabilities_refuses_until_the_terms_are_accepted(tmp_path, monkeypatch):
    _site(download=True, unblock=True)
    monkeypatch.setattr(ytdl_attestation, "accepted", lambda who, path=None: False)
    deps = ex.Deps({"dashboard_url": "http://d", "dashboard_token": "t"},
                   editor_fn=lambda: "editor2",
                   identity_token_fn=lambda: "v2.identity.token")
    cap = ex.capabilities(deps)
    assert cap["ok"] is False and cap["reason"] == ex.REASON_NOT_ATTESTED


def test_capabilities_refuses_without_a_signed_identity_token():
    """H5: the fleet routes verify the token, so a machine that cannot present
    one has no capability -- and saying so here is what stops the SPA
    dispatching a job that is about to 403."""
    _site(download=True, unblock=True)
    deps = ex.Deps({"dashboard_url": "http://d", "dashboard_token": "t"},
                   editor_fn=lambda: "editor2", identity_token_fn=lambda: "")
    cap = ex.capabilities(deps)
    assert cap["ok"] is False and cap["reason"] == ex.REASON_NO_IDENTITY
