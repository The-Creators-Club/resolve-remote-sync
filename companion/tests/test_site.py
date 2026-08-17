"""The site manifest (site.py) and what reads it.

The contract under test is the one the dashboard publishes at
GET /api/v1/site (schema 1, unauthenticated, no secrets) and the promise
every consumer makes about it: a dashboard that predates it answers 404, and
NOTHING may break -- the caller falls back to its flag/config value.
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import drive_swap
from ccsync_companion import site as site_mod


GOOD = {
    "schema": 1,
    "org_name": "Example Post",
    "tree_name": "Tree",
    "canonical_prefix": "P:\\",
    "remote_root": "/volume1/Media/Tree",
    "smb_unc": "\\\\nas\\Media\\Tree",
    "sftp_host": "nas.example.ts.net",
    "sftp_port": 2222,
    "rclone_remote": "example_sftp",
    "nas_syncthing_id": "AAAAAAA-BBBBBBB",
    "dashboard_url": "http://nas.example:8480",
    "template_folders": ["Footage", "Audio"],
    "shared_asset_folders": ["Assets"],
    "nas_kind": "synology",
    "sftp_chunk_size": "64Ki",
    "sftp_concurrency": 32,
    "sftp_shell_type": "none",
}


class _Resp:
    """Minimal stand-in for what urlopen returns: a context manager with
    read() and a status."""

    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(resp):
    def _open(url, timeout):
        _open.calls.append((url, timeout))
        if isinstance(resp, Exception):
            raise resp
        return resp
    _open.calls = []
    return _open


# -- normalise ---------------------------------------------------------------

def test_a_good_manifest_survives_normalisation_intact():
    site = site_mod.normalise(GOOD)
    assert site["smb_unc"] == "\\\\nas\\Media\\Tree"
    assert site["sftp_port"] == 2222
    assert site["template_folders"] == ["Footage", "Audio"]
    assert site["nas_kind"] == "synology"


def test_every_string_may_be_unset():
    """"" is a legitimate value for every string: the server simply has not
    been told. Consumers fall back; none of them may see a KeyError."""
    site = site_mod.normalise({"schema": 1})
    assert site is not None
    for key in site_mod.STRING_KEYS:
        assert site[key] == ""
    assert site["sftp_port"] == 22
    assert site["template_folders"] == []


def test_a_wrongly_typed_field_is_coerced_not_propagated():
    """A server answering {"sftp_port": "22"} or a bare string where a list
    belongs must not crash an installer three steps later with a message
    about something else."""
    site = site_mod.normalise({
        "schema": 1, "sftp_port": "not a number", "template_folders": "Footage",
        "smb_unc": 5, "tree_name": "  Tree  ",
    })
    assert site["sftp_port"] == 22
    assert site["template_folders"] == []
    assert site["smb_unc"] == ""
    assert site["tree_name"] == "Tree"


def test_an_unusable_body_is_refused():
    assert site_mod.normalise(None) is None
    assert site_mod.normalise([1, 2]) is None
    assert site_mod.normalise({}) is None            # no schema at all
    assert site_mod.normalise({"schema": 0}) is None
    assert site_mod.normalise({"schema": "one"}) is None
    # a NEWER schema is additive by contract -- read the keys we know
    assert site_mod.normalise({"schema": 2, "tree_name": "T"})["tree_name"] == "T"


# -- fetch -------------------------------------------------------------------

def test_fetch_asks_the_documented_path():
    opener = _opener(_Resp(GOOD))
    site = site_mod.fetch_site("http://dash.example:8480/", http_open=opener)
    assert site["rclone_remote"] == "example_sftp"
    assert opener.calls[0][0] == "http://dash.example:8480/api/v1/site"


def test_an_older_dashboard_404s_and_that_is_not_an_error():
    """The whole rollout depends on this: every consumer degrades to its own
    flag/config value rather than failing the install."""
    err = urllib.error.HTTPError("http://x/api/v1/site", 404, "Not Found", {}, io.BytesIO(b""))
    assert site_mod.fetch_site("http://dash.example:8480", http_open=_opener(err)) is None


def test_a_dead_network_is_not_an_error_either():
    assert site_mod.fetch_site("http://dash.example:8480",
                               http_open=_opener(TimeoutError("timed out"))) is None


def test_a_blank_dashboard_url_never_leaves_the_machine():
    """The companion must not phone anywhere when nobody configured it
    (2026-08-17): with no dashboard_url there is no request at all."""
    opener = _opener(_Resp(GOOD))
    assert site_mod.fetch_site("", http_open=opener) is None
    assert site_mod.fetch_site("   ", http_open=opener) is None
    assert opener.calls == []


def test_a_redirected_manifest_is_refused():
    """upgrade.py's discipline, for the same reason: "where is your NAS" is
    exactly the answer that must not be redirectable to somebody else."""
    assert site_mod.fetch_site("http://dash.example:8480",
                               http_open=_opener(_Resp(GOOD, status=302))) is None


def test_a_body_that_is_not_the_manifest_is_refused():
    assert site_mod.fetch_site("http://d:8480", http_open=_opener(_Resp(b"<html>"))) is None
    assert site_mod.fetch_site("http://d:8480", http_open=_opener(_Resp({"ok": True}))) is None


# -- cache -------------------------------------------------------------------

def test_the_cache_round_trips_under_the_state_dir():
    assert site_mod.site_path() == config_mod.CONFIG_DIR / "state" / "site.json"
    assert site_mod.cached_site() is None
    assert site_mod.save_site(site_mod.normalise(GOOD)) is True
    assert site_mod.cached_site()["smb_unc"] == "\\\\nas\\Media\\Tree"


def test_an_offline_start_still_has_last_known_values():
    site_mod.save_site(site_mod.normalise(GOOD))
    site = site_mod.refresh_site("http://dash.example:8480",
                                 http_open=_opener(TimeoutError("no route")))
    assert site["nas_syncthing_id"] == "AAAAAAA-BBBBBBB"


def test_a_fresh_answer_replaces_the_cache():
    site_mod.save_site(site_mod.normalise(GOOD))
    newer = dict(GOOD, smb_unc="\\\\nas2\\Media\\Tree")
    site = site_mod.refresh_site("http://dash.example:8480", http_open=_opener(_Resp(newer)))
    assert site["smb_unc"] == "\\\\nas2\\Media\\Tree"
    assert site_mod.cached_site()["smb_unc"] == "\\\\nas2\\Media\\Tree"


def test_the_cache_age_is_the_files_mtime_not_a_field_in_it():
    """A site.json copied from another machine carries that machine's
    _fetched_at; the mtime is the only honest age."""
    site_mod.save_site(site_mod.normalise(GOOD))
    path = site_mod.site_path()
    old = time.time() - 3600
    os.utime(path, (old, old))
    assert site_mod.cached_site(max_age_seconds=60) is None
    assert site_mod.cached_site(max_age_seconds=7200)["tree_name"] == "Tree"
    assert site_mod.cached_site() is not None  # no ceiling asked for: stale beats nothing


def test_a_corrupt_cache_reads_as_absent():
    path = site_mod.site_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert site_mod.cached_site() is None


# -- what the manifest actually changes: the grade swap's UNC -----------------

def test_config_takes_the_smb_unc_from_the_manifest(tmp_path):
    """WP0 step 3: the companion reads smb_unc into server_p_unc instead of
    deriving it -- a NAS whose SMB share name differs from its SFTP path
    cannot be derived at all."""
    site_mod.save_site(site_mod.normalise(GOOD))
    path = tmp_path / "config.toml"
    path.write_text('local_root = "C:\\\\x"\n', encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert cfg["server_p_unc"] == "\\\\nas\\Media\\Tree"


def test_an_explicit_server_p_unc_beats_the_manifest(tmp_path):
    site_mod.save_site(site_mod.normalise(GOOD))
    path = tmp_path / "config.toml"
    path.write_text('server_p_unc = "\\\\\\\\other\\\\Share"\n', encoding="utf-8")
    assert config_mod.load_config(path)["server_p_unc"] == "\\\\other\\Share"

    # ...including the kill switch, which the manifest must not un-set
    path.write_text('server_p_unc = "off"\n', encoding="utf-8")
    assert config_mod.load_config(path)["server_p_unc"] == "off"


def test_no_manifest_leaves_the_derivation_in_charge(tmp_path):
    """A TrueNAS install that has never seen a manifest behaves exactly as it
    did before this existed."""
    path = tmp_path / "config.toml"
    path.write_text('local_root = "C:\\\\x"\n', encoding="utf-8")
    assert config_mod.load_config(path)["server_p_unc"] == ""


def test_derive_server_unc_knows_both_nas_conventions():
    f = drive_swap.derive_server_unc
    # TrueNAS: everything past /mnt/<pool> is the SMB path
    assert f("http://192.168.0.10:8480", "/mnt/tank/Pool/Tree") == "\\\\192.168.0.10\\Pool\\Tree"
    # Synology: the shared folder is the first component under /volumeN
    assert f("http://nas:8480", "/volume1/Media/Tree") == "\\\\nas\\Media\\Tree"
    assert f("http://nas:8480", "/volume12/Media/Tree/") == "\\\\nas\\Media\\Tree"
    # underivable -> "" (feature hidden, never a broken UNC)
    assert f("http://nas:8480", "/volume1") == ""
    assert f("http://nas:8480", "/srv/Media/Tree") == ""
    assert f("", "/volume1/Media/Tree") == ""


# -- transport tuning the NAS platform dictates (Synology spike 6) -----------

def _load(tmp_path, body=""):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return config_mod.load_config(path)


def test_the_site_sets_the_sftp_chunk_size_a_client_cannot_discover(tmp_path):
    """DSM 7.2's OpenSSH 8.2p1 has no limits@openssh.com: the fleet default
    of 255Ki TRUNCATES every download at 539,000,832 bytes there, silently.
    Only the server knows which NAS this is."""
    assert config_mod.DEFAULTS["sftp_chunk_size"] == "255Ki"
    site_mod.save_site(site_mod.normalise(GOOD))
    cfg = _load(tmp_path, 'local_root = "C:\\\\x"\n')
    assert cfg["sftp_chunk_size"] == "64Ki"
    assert cfg["sftp_concurrency"] == 32


def test_an_explicit_chunk_size_beats_the_site(tmp_path):
    site_mod.save_site(site_mod.normalise(GOOD))
    cfg = _load(tmp_path, 'sftp_chunk_size = "128Ki"\nsftp_concurrency = 8\n')
    assert cfg["sftp_chunk_size"] == "128Ki"
    assert cfg["sftp_concurrency"] == 8


def test_an_explicit_OFF_beats_the_site_too(tmp_path):
    """"" and 0 disable the flag entirely (see DEFAULTS' transport-tuning
    block) -- a MEANINGFUL setting, not an absent one, so the site must not
    overwrite it. This is why these keys test for PRESENCE, not truthiness."""
    site_mod.save_site(site_mod.normalise(GOOD))
    cfg = _load(tmp_path, 'sftp_chunk_size = ""\nsftp_concurrency = 0\n')
    assert cfg["sftp_chunk_size"] == ""
    assert cfg["sftp_concurrency"] == 0


def test_a_site_that_says_nothing_leaves_the_measured_defaults_alone(tmp_path):
    """"" / 0 from the SERVER means "not specified" -- the dashboard has no
    business switching an editor's transport tuning off."""
    site_mod.save_site(site_mod.normalise(
        dict(GOOD, sftp_chunk_size="", sftp_concurrency=0)))
    cfg = _load(tmp_path, 'local_root = "C:\\\\x"\n')
    assert cfg["sftp_chunk_size"] == config_mod.DEFAULTS["sftp_chunk_size"]
    assert cfg["sftp_concurrency"] == config_mod.DEFAULTS["sftp_concurrency"]


def test_the_sites_chunk_size_reaches_the_actual_rclone_flags(tmp_path):
    """The whole point: lanes A and B are what truncate. RcloneTuning reads
    the merged config, so the manifest lands on the command line."""
    from ccsync_companion.sync.rclone_lane import RcloneTuning

    site_mod.save_site(site_mod.normalise(GOOD))
    flags = RcloneTuning.from_cfg(_load(tmp_path, 'local_root = "C:\\\\x"\n')).flags("down")
    assert flags[flags.index("--sftp-chunk-size") + 1] == "64Ki"
    assert flags[flags.index("--sftp-concurrency") + 1] == "32"


def test_the_shell_type_is_carried_for_the_installers(tmp_path):
    """Not a companion setting at all -- both bootstraps read it when they
    write the rclone stanza. A DSM editor's shell is /sbin/nologin, so
    rclone's `shell_type = unix` (which runs md5sum over SSH to verify a
    transfer) fails on every check there."""
    site_mod.save_site(site_mod.normalise(GOOD))
    assert site_mod.cached_site()["sftp_shell_type"] == "none"
    # ...and it is NOT a config.toml key: the companion has no use for it.
    assert "sftp_shell_type" not in config_mod.DEFAULTS


def test_no_manifest_at_all_leaves_the_measured_defaults_alone(tmp_path):
    cfg = _load(tmp_path, 'local_root = "C:\\\\x"\n')
    assert cfg["sftp_chunk_size"] == config_mod.DEFAULTS["sftp_chunk_size"]
    assert cfg["sftp_concurrency"] == config_mod.DEFAULTS["sftp_concurrency"]


@pytest.mark.parametrize("port", [22, 2222])
def test_the_sftp_port_survives_the_round_trip(port):
    """Synology commonly runs SSH on a non-22 port; the rclone stanza needs
    the number, so it must not be lost in the cache."""
    site_mod.save_site(site_mod.normalise(dict(GOOD, sftp_port=port)))
    assert site_mod.cached_site()["sftp_port"] == port
