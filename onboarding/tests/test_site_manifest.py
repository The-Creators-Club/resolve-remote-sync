"""The wizard's half of the site manifest (WP0/WP5, 2026-08-17).

Nothing tenant-shaped is compiled into this installer any more: the NAS
Syncthing device ID, the rclone remote name, the SSH port and the NAS-side
tree root all come from GET {dashboard_url}/api/v1/site. The contract these
tests pin is the DEGRADATION: a dashboard old enough to 404 on the manifest
must still produce a working install, with the flags/fallbacks it always had.
"""

from __future__ import annotations

import urllib.error

import steps
from ccsync_companion import site as site_mod


SITE = {
    "schema": 1,
    "tree_name": "Tree",
    "remote_root": "/volume1/Media/Tree",
    "smb_unc": "\\\\nas\\Media\\Tree",
    "sftp_host": "nas.example.ts.net",
    "sftp_port": 2222,
    "rclone_remote": "acme_sftp",
    "nas_syncthing_id": "AAAAAAA-BBBBBBB",
    "nas_kind": "synology",
}


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _get(payload):
    def _http_get(url, timeout):
        _http_get.calls.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload
    _http_get.calls = []
    return _http_get


# -- fetch --------------------------------------------------------------------

def test_fetch_site_asks_the_documented_path(tmp_path, monkeypatch):
    monkeypatch.setattr(site_mod.config_mod, "CONFIG_DIR", tmp_path / ".ccsync")
    http_get = _get(SITE)
    site = steps.fetch_site("http://dash.example:8480/", http_get=http_get)
    assert site["rclone_remote"] == "acme_sftp"
    assert http_get.calls == ["http://dash.example:8480/api/v1/site"]


def test_fetch_site_caches_for_the_companion(tmp_path, monkeypatch):
    """The wizard is the one process guaranteed to have just talked to the
    dashboard; the companion reads this file offline (site.py)."""
    monkeypatch.setattr(site_mod.config_mod, "CONFIG_DIR", tmp_path / ".ccsync")
    steps.fetch_site("http://dash.example:8480", http_get=_get(SITE))
    assert site_mod.cached_site()["smb_unc"] == "\\\\nas\\Media\\Tree"


def test_an_older_dashboard_yields_an_empty_manifest_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(site_mod.config_mod, "CONFIG_DIR", tmp_path / ".ccsync")
    err = urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
    assert steps.fetch_site("http://dash.example:8480", http_get=_get(err)) == {}
    assert steps.fetch_site("http://dash.example:8480", http_get=_get(TimeoutError())) == {}
    assert steps.fetch_site("http://dash.example:8480", http_get=_get({"nope": 1})) == {}


def test_no_dashboard_url_means_no_request_at_all():
    http_get = _get(SITE)
    assert steps.fetch_site("", http_get=http_get) == {}
    assert http_get.calls == []


# -- what the wizard does with it ---------------------------------------------

def test_the_windows_bootstrap_is_told_the_sites_own_values(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeResult(stdout="")

    steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="tok", tailnet_host="dash.example",
        dashboard_url="http://dash.example:8480", run=fake_run, script_path=script,
        platform="win32", site=SITE,
    )
    cmd = captured["cmd"]
    # the SFTP host the SITE names beats the one derived from the dashboard URL
    assert cmd[cmd.index("-TailnetHost") + 1] == "nas.example.ts.net"
    assert cmd[cmd.index("-RemoteRoot") + 1] == "/volume1/Media/Tree"
    assert cmd[cmd.index("-NasSyncthingId") + 1] == "AAAAAAA-BBBBBBB"
    assert cmd[cmd.index("-SftpPort") + 1] == "2222"
    # the device ID rides the environment too, for the .sh (no flag) and for
    # anyone re-running the script by hand
    assert captured["kwargs"]["env"]["CCSYNC_NAS_SYNCTHING_ID"] == "AAAAAAA-BBBBBBB"


def test_without_a_manifest_the_bootstrap_keeps_its_own_defaults(tmp_path):
    """The 404 case: no flags are invented, so the script's own -RemoteRoot /
    -NasSyncthingId handling (which fetches, then refuses) decides."""
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="tok", tailnet_host="dash.example",
        dashboard_url="http://dash.example:8480",
        run=lambda cmd, **kw: captured.setdefault("cmd", cmd) or _FakeResult(),
        script_path=script, platform="win32",
    )
    cmd = captured["cmd"]
    assert "-RemoteRoot" not in cmd
    assert "-NasSyncthingId" not in cmd
    assert "-SftpPort" not in cmd
    assert cmd[cmd.index("-TailnetHost") + 1] == "dash.example"


def test_the_mac_bootstrap_gets_the_same_values(tmp_path):
    script = tmp_path / "macos_bootstrap.sh"
    script.write_text("# fake")
    captured = {}

    steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="tok", tailnet_host="dash.example",
        dashboard_url="http://dash.example:8480",
        run=lambda cmd, **kw: captured.setdefault("cmd", cmd) or _FakeResult(),
        script_path=script, platform="darwin", site=SITE,
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--tailnet-host") + 1] == "nas.example.ts.net"
    assert cmd[cmd.index("--remote-root") + 1] == "/volume1/Media/Tree"
    assert cmd[cmd.index("--sftp-port") + 1] == "2222"


def test_port_22_is_never_passed_because_it_is_the_default(tmp_path):
    """Only a NON-22 port is worth a flag -- DSM commonly moves SSH, TrueNAS
    does not, and an explicit 22 everywhere would just be noise in the log."""
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}
    steps.run_bootstrap(
        editor_name="j", dashboard_token="t", tailnet_host="h",
        run=lambda cmd, **kw: captured.setdefault("cmd", cmd) or _FakeResult(),
        script_path=script, platform="win32", site=dict(SITE, sftp_port=22),
    )
    assert "-SftpPort" not in captured["cmd"]


def test_a_junk_port_in_the_manifest_does_not_reach_the_installer(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}
    steps.run_bootstrap(
        editor_name="j", dashboard_token="t", tailnet_host="h",
        run=lambda cmd, **kw: captured.setdefault("cmd", cmd) or _FakeResult(),
        script_path=script, platform="win32", site=dict(SITE, sftp_port="ssh"),
    )
    assert "-SftpPort" not in captured["cmd"]


# -- the defaults that are gone -----------------------------------------------

def test_no_dashboard_address_is_compiled_in():
    """The grep gate in prose: a fresh checkout of this installer names no
    deployment at all (WP0). CCSYNC_DASHBOARD_URL is the scripted-install
    escape hatch, and this process was not given one."""
    assert steps.DEFAULT_DASHBOARD_URL == ""
    assert steps.DEFAULT_BASE_DASHBOARD_URL == ""
    assert steps.DEFAULT_REMOTE_ROOT == ""
    assert steps.DEFAULT_BASE_LOCAL_ROOT_MACOS == ""


# -- the rclone remote NAME (2026-08-17, COMMERCIAL_READINESS.md item 11) ----
#
# The wizard writes config.toml's `remote`, and it must match the stanza in
# rclone.conf or every lane fails with "didn't find section in config file".
# The existing fleet's stanza is `[creators_club_sftp]`, written before the
# manifest existed, so a re-run against a dashboard that publishes no
# rclone_remote must NOT rename it to the neutral default.

def _write_config(tmp_path, body, site, role="editor"):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    steps.ensure_config(role, editor_name="jane", dashboard_url="http://d:8480",
                        dashboard_token="tok", local_root=r"C:\Tree",
                        config_path=path, site=site, platform="win32")
    return path.read_text(encoding="utf-8")


def test_the_sites_remote_name_wins(tmp_path):
    text = _write_config(tmp_path, 'remote = "creators_club_sftp"\n', SITE)
    assert 'remote = "acme_sftp"' in text


def test_an_existing_remote_name_survives_a_manifest_that_omits_it(tmp_path):
    """The pre-manifest fleet. Renaming this to ccsync_sftp would point the
    companion at a stanza rclone.conf does not have."""
    site = {k: v for k, v in SITE.items() if k != "rclone_remote"}
    text = _write_config(tmp_path, 'remote = "creators_club_sftp"\n', site)
    assert 'remote = "creators_club_sftp"' in text
    assert "ccsync_sftp" not in text


def test_a_blank_remote_name_is_filled_with_the_neutral_default(tmp_path):
    site = {k: v for k, v in SITE.items() if k != "rclone_remote"}
    text = _write_config(tmp_path, 'remote = ""\n', site)
    assert 'remote = "ccsync_sftp"' in text


def test_a_config_with_no_remote_key_at_all_gets_the_neutral_default(tmp_path):
    site = {k: v for k, v in SITE.items() if k != "rclone_remote"}
    text = _write_config(tmp_path, 'local_root = "C:\\Tree"\n', site)
    assert 'remote = "ccsync_sftp"' in text


# -- the LaunchAgent rename (item 10) ---------------------------------------

def test_installing_the_agent_retires_the_legacy_pair(tmp_path):
    """Both labels loaded at once means two companions watching one tree."""
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    for name in steps.LEGACY_PLIST_NAMES:
        (agents / name).write_text("<plist/>", encoding="utf-8")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeResult(returncode=0)

    plist = steps.write_companion_launch_agent(
        tmp_path / "ccsync-companion", agents_dir=agents, run=fake_run)

    assert plist.name == "com.ccsync.companion.plist" and plist.is_file()
    assert not any((agents / name).exists() for name in steps.LEGACY_PLIST_NAMES)
    assert any("bootout" in c for c in calls)
    assert "<string>com.ccsync.companion</string>" in plist.read_text(encoding="utf-8")


def test_retiring_is_a_no_op_on_a_machine_that_never_had_them(tmp_path):
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    calls = []
    assert steps.retire_legacy_launch_agents(
        agents, run=lambda cmd, **kw: calls.append(cmd)) == []
    assert calls == []


def test_the_uninstaller_still_knows_the_legacy_names(tmp_path):
    """An install made before the rename must stay fully removable."""
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    legacy = agents / steps.LEGACY_COMPANION_PLIST_NAME
    legacy.write_text("<plist/>", encoding="utf-8")
    plan = steps.build_cleanup_plan_macos(home=tmp_path)
    assert legacy in plan.launch_agent_plists
