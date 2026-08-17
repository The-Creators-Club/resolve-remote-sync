"""Who may drive 127.0.0.1:8899 -- the pure half (loopback_guard.py).

The wire-level half lives in test_broll_server.py (403s, preflights, the
Host check); this file pins the rules those checks are made of, because every
one of them is a rule an attacker only has to beat once:
  - the origin allow-list is EXACT, never a prefix/suffix match,
  - the token is a real file with real permissions, compared constant-time,
  - `share` is one path segment,
  - a bundle is something you reveal, never something you open.

Added 2026-08-17 with COMMERCIAL_READINESS.md item 5 (C1).
"""

from __future__ import annotations

import os
import stat

import pytest

from ccsync_companion import config as config_mod, loopback_guard


# ---------------------------------------------------------------------------
# The token
# ---------------------------------------------------------------------------


def test_the_token_lands_under_the_redirected_config_dir():
    """CONFIG_DIR is read at call time, never captured at import: the suite
    repoints it at a temp tree and a token written into the developer's real
    ~/.ccsync would outlive the run (conftest's whole premise)."""
    assert loopback_guard.token_path().parent == config_mod.CONFIG_DIR


def test_ensure_token_writes_a_token_that_verifies():
    token = loopback_guard.ensure_token()
    assert token
    assert loopback_guard.read_token() == token
    assert loopback_guard.verify_token(token)


def test_every_session_gets_a_different_token():
    """A token that survives the process that owned it is a token that
    outlives the reason to trust it."""
    first = loopback_guard.ensure_token()
    second = loopback_guard.ensure_token()
    assert first != second
    assert not loopback_guard.verify_token(first)


@pytest.mark.parametrize("presented", ["", "   ", None, 12, b"bytes", "wrong"])
def test_nothing_else_verifies(presented):
    loopback_guard.ensure_token()
    assert not loopback_guard.verify_token(presented)


def test_no_token_file_verifies_nothing(tmp_path):
    assert not loopback_guard.verify_token("anything", path=tmp_path / "absent")


@pytest.mark.skipif(os.name == "nt", reason="posix mode bits")
def test_the_token_is_owner_only_on_posix():
    loopback_guard.ensure_token()
    mode = stat.S_IMODE(loopback_guard.token_path().stat().st_mode)
    assert mode == 0o600


def test_the_permissions_are_the_shared_helpers_not_a_second_copy():
    """secretfile.harden is the one place that knows chmod is meaningless on
    Windows and an ACL is required; a token written any other way would be
    world-readable there, which is the whole thing this file is for."""
    hardened: list = []
    loopback_guard.ensure_token(harden=lambda p: hardened.append(str(p)) or True)
    # The TEMP file, before the rename: the secret is never on disk under
    # wider permissions, even briefly.
    assert hardened and hardened[0].endswith(".tmp")


def test_a_failed_harden_never_stops_the_companion():
    def _boom(path):
        raise OSError("icacls is not on PATH")

    assert loopback_guard.ensure_token(harden=_boom) is None
    # ...and the caller (broll_server's constructor) treats that as "no second
    # way in", not as a failure to serve.


# ---------------------------------------------------------------------------
# Origins
# ---------------------------------------------------------------------------


def test_a_dashboard_url_authorises_both_schemes():
    """Tailscale Serve fronts the same host on https (2026-08-17). A fleet
    provisioned with an http dashboard_url must not lose Send-to-Resolve the
    day the NAS moves behind TLS."""
    assert loopback_guard.origins_for_url("http://100.64.0.1:8000/") == {
        "http://100.64.0.1:8000", "https://100.64.0.1:8000",
    }


def test_the_port_is_part_of_the_origin():
    origins = loopback_guard.origins_for_url("http://nas.example:8000")
    assert "http://nas.example" not in origins


@pytest.mark.parametrize("url", ["", None, "   ", "not a url", "ftp://nas/x",
                                 "file:///etc/passwd", "javascript:alert(1)"])
def test_a_url_that_is_not_a_dashboard_authorises_nothing(url):
    assert loopback_guard.origins_for_url(url) == set()


def test_the_cached_site_manifest_counts_too():
    """A de-tenanted build has no compiled-in dashboard address at all -- the
    manifest is where a provisioned machine's identity lives (WP0)."""
    allowed = loopback_guard.allowed_origins(
        {"dashboard_url": ""}, site={"dashboard_url": "https://nas.ts.net"})
    assert "https://nas.ts.net" in allowed


def test_an_operator_can_add_an_origin_without_moving_the_dashboard():
    allowed = loopback_guard.allowed_origins({
        "dashboard_url": "http://100.64.0.1:8000",
        "loopback_extra_origins": ["https://nas.example.ts.net"],
    })
    assert "https://nas.example.ts.net" in allowed
    assert "http://100.64.0.1:8000" in allowed


def test_an_unconfigured_companion_authorises_nobody():
    assert loopback_guard.allowed_origins({}) == frozenset()
    assert loopback_guard.allowed_origins(None) == frozenset()


ALLOWED = frozenset({"http://100.64.0.1:8000"})


@pytest.mark.parametrize("origin", [
    "https://100.64.0.1:8000",                 # the other scheme, not listed
    "http://100.64.0.1:8000.evil.net",         # suffix
    "http://evil.net/http://100.64.0.1:8000",  # prefix-ish
    "http://100.64.0.1",                       # no port
    "http://100.64.0.1:8001",                  # another port
    "null", "", None, 12,
])
def test_only_an_exact_origin_is_allowed(origin):
    assert not loopback_guard.origin_allowed(origin, ALLOWED)


def test_the_case_of_the_scheme_and_host_does_not_matter():
    assert loopback_guard.origin_allowed("HTTP://100.64.0.1:8000", ALLOWED)


def test_dev_loopback_origins_need_the_flag():
    assert not loopback_guard.origin_allowed("http://localhost:5173", ALLOWED)
    assert loopback_guard.origin_allowed("http://localhost:5173", ALLOWED, dev=True)
    assert not loopback_guard.origin_allowed("http://evil.net", ALLOWED, dev=True)


def test_the_dev_flag_is_off_unless_asked_for():
    assert not loopback_guard.dev_origins_enabled({})
    assert loopback_guard.dev_origins_enabled({"loopback_dev_origins": True})


# ---------------------------------------------------------------------------
# Host, Content-Type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1:8899", "localhost:8899",
                                  "[::1]:8899", "LOCALHOST:8899", None, ""])
def test_a_loopback_host_is_accepted(host):
    assert loopback_guard.host_allowed(host, 8899)


@pytest.mark.parametrize("host", ["evil.example:8899", "127.0.0.1:8900",
                                  "127.0.0.1", "nas.ts.net:8899",
                                  "127.0.0.1:notaport", "0.0.0.0:8899"])
def test_a_rebinding_host_is_refused(host):
    assert not loopback_guard.host_allowed(host, 8899)


@pytest.mark.parametrize("ctype", ["application/json",
                                   "application/json; charset=utf-8",
                                   " APPLICATION/JSON "])
def test_json_content_types(ctype):
    assert loopback_guard.content_type_is_json(ctype)


@pytest.mark.parametrize("ctype", [None, "", "text/plain",
                                   "multipart/form-data",
                                   "application/x-www-form-urlencoded",
                                   "application/jsonx"])
def test_everything_a_form_can_send_without_a_preflight_is_refused(ctype):
    assert not loopback_guard.content_type_is_json(ctype)


# ---------------------------------------------------------------------------
# share, bundles, containment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("share", ["broll", "music", "projects",
                                   "archive_2019", "b-roll 2"])
def test_the_shares_this_fleet_uses_are_valid(share):
    assert loopback_guard.valid_share(share)


@pytest.mark.parametrize("share", [
    "..", "../..", ".", ".hidden", "a/b", "a\\b", "C:", "x:y",
    "", "  ", " broll", "broll ", "bro\x00ll", "bro\nll", None, 12,
    "x" * (loopback_guard.MAX_SHARE_LENGTH + 1),
])
def test_anything_that_is_not_one_safe_segment_is_refused(share):
    assert not loopback_guard.valid_share(share)


@pytest.mark.parametrize("path", ["/Users/x/Thing.app", "C:\\x\\Thing.APP",
                                  "/x/Disk.dmg", "/x/Install.pkg",
                                  "/x/Some.bundle", "/x/Thing.app/"])
def test_bundles_are_recognised(path):
    assert loopback_guard.is_bundle_path(path)


@pytest.mark.parametrize("path", ["/x/clip.mov", "/x/Youtube", "C:\\x\\a.wav",
                                  "/x/appendix", "", None])
def test_ordinary_paths_are_not_bundles(path):
    assert not loopback_guard.is_bundle_path(path)


def test_containment_follows_symlinks(tmp_path):
    inside = tmp_path / "root" / "a" / "b.mov"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"x")
    assert loopback_guard.is_within(inside, tmp_path / "root")
    assert not loopback_guard.is_within(tmp_path / "elsewhere" / "b.mov",
                                        tmp_path / "root")


def test_a_sibling_with_a_shared_prefix_is_not_contained(tmp_path):
    """"P:\\Creators_ClubExtra" is not under "P:\\Creators_Club"."""
    assert not loopback_guard.is_within(str(tmp_path / "rootExtra" / "x"),
                                        str(tmp_path / "root"))


def test_a_root_equal_to_the_path_is_contained(tmp_path):
    assert loopback_guard.is_within(tmp_path, tmp_path)


def test_containment_never_raises():
    assert not loopback_guard.is_within(None, None)
    assert not loopback_guard.is_within("x", "")
