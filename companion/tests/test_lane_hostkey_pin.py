"""Editor lanes pin the NAS SSH host key when the site publishes one (GL-19 /
COM-H15, CR-368, 2026-10-07).

rclone's sftp backend verifies NOTHING unless `known_hosts_file` is set, so both
bootstrap scripts write a known_hosts file from the manifest's `sftp_hostkey`
and point the stanza at it. The macOS half is executed for real (the section of
macos_bootstrap.sh between its step-5 banner and step-6 banner, under bash and
the local awk); the Windows half is pinned as text, because PowerShell's
bootstrap cannot be run end to end on a test machine without installing things.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parent.parent.parent / "installer"
MAC = INSTALLER / "macos_bootstrap.sh"
WIN = INSTALLER / "windows_bootstrap.ps1"
_BASH = shutil.which("bash") or "bash"

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPINNEDKEYPINNEDKEYPINNEDKEYPINNEDKEY00"

needs_bash = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("awk") is None,
    reason="needs bash and awk",
)


def _mac_section() -> str:
    text = MAC.read_text(encoding="utf-8")
    begin = text.index("# 5. rclone remote config stanza")
    begin = text.rfind("# ------", 0, begin)
    end = text.index("# 6. Companion binary")
    end = text.rfind("# ------", 0, end)
    return text[begin:end]


def _mac_function(name: str) -> str:
    text = MAC.read_text(encoding="utf-8")
    start = text.index(f"{name}() {{")
    depth, i = 0, text.index("{", start)
    while True:
        ch = text[i]
        depth += ch == "{"
        depth -= ch == "}"
        i += 1
        if depth == 0:
            return text[start:i] + "\n"


def _rewrite_helper() -> str:
    lines = MAC.read_text(encoding="utf-8").splitlines()
    b = next(i for i, ln in enumerate(lines) if ln.strip() == "# ---CCSYNC-RCLONE-STANZA-BEGIN---")
    e = next(i for i, ln in enumerate(lines) if ln.strip() == "# ---CCSYNC-RCLONE-STANZA-END---")
    return "\n".join(lines[b:e + 1]) + "\n"


def _run_mac_step5(tmp_path: Path, site_json: str, conf_text: str = "", port: str = "22",
                   dry: str = "0", env: dict | None = None):
    home = tmp_path / "home"
    (home / ".ccsync").mkdir(parents=True, exist_ok=True)
    conf = tmp_path / "rclone.conf"
    if conf_text:
        conf.write_text(conf_text, encoding="utf-8")
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "set -u\n"
        'skip() { echo "SKIP: $1"; }\nstep() { echo "STEP: $1"; }\n'
        'warn() { echo "WARN: $1" >&2; }\ndry() { echo "DRY: $1"; }\n'
        'ensure_dir() { mkdir -p "$1"; }\n'
        + _mac_function("site_value")
        + _rewrite_helper()
        + f"SITE_JSON='{site_json}'\n"
        f'DRY_RUN={dry}\nSFTP_PORT={port}\nREMOTE_NAME=creators_club_sftp\n'
        f'TAILNET_HOST=nas.example.ts.net\nEDITOR_NAME=editor1\n'
        f'KEY_FILE_PATH={home.as_posix()}/.ssh/ccsync_ed25519\n'
        f'CCSYNC_CONFIG_DIR={home.as_posix()}/.ccsync\n'
        f'RCLONE_CONF_DIR={tmp_path.as_posix()}\nRCLONE_CONF_PATH={conf.as_posix()}\n'
        + _mac_section(),
        encoding="utf-8",
    )
    import os
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("CCSYNC_SFTP_")}
    child_env.update(env or {})
    result = subprocess.run([_BASH, str(harness)], capture_output=True, encoding="utf-8",
                            errors="replace", timeout=60, env=child_env)
    return result, conf, home / ".ccsync" / "nas_known_hosts"


@needs_bash
def test_a_published_host_key_is_written_and_the_stanza_points_at_it(tmp_path):
    result, conf, known = _run_mac_step5(tmp_path, f'{{"sftp_hostkey": "{KEY}"}}')
    assert result.returncode == 0, result.stderr
    assert known.read_text(encoding="utf-8") == f"nas.example.ts.net {KEY}\n"
    text = conf.read_text(encoding="utf-8")
    assert f"known_hosts_file = {known.as_posix()}" in text
    # rclone prefers ECDSA; without this the pinned ed25519 key is a mismatch
    assert "host_key_algorithms = ssh-ed25519" in text
    assert "host = nas.example.ts.net" in text and "shell_type = unix" in text


@needs_bash
def test_a_non_default_port_is_spelled_the_known_hosts_way(tmp_path):
    result, conf, known = _run_mac_step5(tmp_path, f'{{"sftp_hostkey": "{KEY}"}}', port="2222")
    assert result.returncode == 0, result.stderr
    assert known.read_text(encoding="utf-8") == f"[nas.example.ts.net]:2222 {KEY}\n"


@needs_bash
def test_no_published_key_leaves_the_stanza_exactly_as_it_always_was(tmp_path):
    result, conf, known = _run_mac_step5(tmp_path, '{"sftp_shell_type": "unix"}')
    assert result.returncode == 0, result.stderr
    assert not known.exists()
    assert "known_hosts_file" not in conf.read_text(encoding="utf-8")
    assert "publishes no NAS SSH host key" in result.stdout


@needs_bash
def test_an_old_stanza_without_the_pin_is_rewritten_and_other_remotes_survive(tmp_path):
    old = (
        "[creators_club_sftp]\ntype = sftp\nhost = nas.example.ts.net\nuser = editor1\n"
        "port = 22\nkey_file = /k\nshell_type = unix\n\n[other]\ntype = s3\nsecret = x\n"
    )
    result, conf, known = _run_mac_step5(tmp_path, f'{{"sftp_hostkey": "{KEY}"}}', conf_text=old)
    assert result.returncode == 0, result.stderr
    text = conf.read_text(encoding="utf-8")
    assert f"known_hosts_file = {known.as_posix()}" in text
    assert "[other]" in text and "secret = x" in text
    # ... and a stanza that already has the pin is left alone
    result2, conf2, _ = _run_mac_step5(tmp_path, f'{{"sftp_hostkey": "{KEY}"}}',
                                       conf_text=text)
    assert "already has a correct" in result2.stdout


@needs_bash
def test_a_dry_run_writes_nothing(tmp_path):
    result, conf, known = _run_mac_step5(tmp_path, f'{{"sftp_hostkey": "{KEY}"}}', dry="1")
    assert result.returncode == 0, result.stderr
    assert not known.exists()
    assert "would write the NAS host key" in result.stdout


def test_the_windows_bootstrap_carries_the_same_pin():
    text = WIN.read_text(encoding="utf-8")
    assert 'Get-SiteValue "sftp_hostkey"' in text
    assert "known_hosts_file = $KnownHostsPath" in text
    assert r"$env:USERPROFILE\.ccsync\nas_known_hosts" in text
    # a stanza without the pin is rewritten, like a wrong host or user
    assert "$existingKnownHosts -ceq $KnownHostsPath" in text
    assert "host_key_algorithms = $KnownHostsAlgo" in text
    assert "$existingKhAlgo -ceq $KnownHostsAlgo" in text
    # the non-default port spelling
    assert '"[$TailnetHost]:$SftpPort"' in text


@needs_bash
def test_a_pinned_stanza_missing_the_algorithm_is_rewritten(tmp_path):
    kh = (tmp_path / "home" / ".ccsync" / "nas_known_hosts").as_posix()
    old = (
        "[creators_club_sftp]\ntype = sftp\nhost = nas.example.ts.net\nuser = editor1\n"
        f"port = 22\nkey_file = /k\nshell_type = unix\nknown_hosts_file = {kh}\n"
    )
    result, conf, _ = _run_mac_step5(tmp_path, f'{{"sftp_hostkey": "{KEY}"}}', conf_text=old)
    assert result.returncode == 0, result.stderr
    assert "host_key_algorithms = ssh-ed25519" in conf.read_text(encoding="utf-8")


@needs_bash
def test_an_rsa_pin_negotiates_as_rsa_sha2_not_sha1_ssh_rsa(tmp_path):
    # CR-368 round 2 (2026-10-07): OpenSSH 8.8+ (TrueNAS 25.x) offers no
    # SHA-1 "ssh-rsa" host-key algorithm.
    rsa = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQRSAPINNEDKEYPINNEDKEY00"
    result, conf, known = _run_mac_step5(tmp_path, f'{{"sftp_hostkey": "{rsa}"}}')
    assert result.returncode == 0, result.stderr
    text = conf.read_text(encoding="utf-8")
    assert "host_key_algorithms = rsa-sha2-512 rsa-sha2-256" in text
    assert "host_key_algorithms = ssh-rsa" not in text
    assert known.read_text(encoding="utf-8").startswith("nas.example.ts.net ssh-rsa ")


def test_the_windows_bootstrap_maps_an_rsa_pin_the_same_way():
    text = WIN.read_text(encoding="utf-8")
    assert "'rsa-sha2-512 rsa-sha2-256'" in text and "-eq 'ssh-rsa'" in text


# -- audit 2026-11-10 ops-install-1: the wizard hands these over; the script's own fetch may fail --

@needs_bash
def test_the_wizards_host_key_and_shell_type_are_used_when_the_scripts_own_fetch_failed(tmp_path):
    """The bootstrap fetches the manifest itself and that fetch is allowed to
    fail. With no manifest it wrote a stanza with NO known_hosts_file, i.e.
    lanes that trust any host key, on an install the wizard reported green."""
    result, conf, known = _run_mac_step5(
        tmp_path, "", env={"CCSYNC_SFTP_HOSTKEY": KEY, "CCSYNC_SFTP_SHELL_TYPE": "none"})
    assert result.returncode == 0, result.stderr
    assert known.read_text(encoding="utf-8") == f"nas.example.ts.net {KEY}\n"
    text = conf.read_text(encoding="utf-8")
    assert f"known_hosts_file = {known.as_posix()}" in text
    assert "shell_type = none" in text


@needs_bash
def test_a_hand_run_with_no_such_variables_reads_the_manifest_as_before(tmp_path):
    result, conf, known = _run_mac_step5(
        tmp_path, f'{{"sftp_hostkey": "{KEY}", "sftp_shell_type": "none"}}')
    assert result.returncode == 0, result.stderr
    assert known.exists() and "shell_type = none" in conf.read_text(encoding="utf-8")


def test_both_scripts_read_the_three_keys_from_the_wizard_before_their_own_fetch():
    mac = MAC.read_text(encoding="utf-8")
    win = WIN.read_text(encoding="utf-8")
    for name, key in (("CCSYNC_RCLONE_REMOTE", "rclone_remote"),
                      ("CCSYNC_SFTP_SHELL_TYPE", "sftp_shell_type"),
                      ("CCSYNC_SFTP_HOSTKEY", "sftp_hostkey")):
        assert mac.index("${" + name + ":-}") < mac.index(f'"$(site_value {key})"'), name
        assert win.index(f'"$env:{name}".Trim()') < win.index(f'Get-SiteValue "{key}"'), name
        # and the manifest is still the fallback, so a hand-run is unchanged
        assert mac.count(f'"$(site_value {key})"') == 1 and win.count(f'Get-SiteValue "{key}"') == 1


def test_the_manifest_the_wizard_holds_keeps_the_host_key():
    from ccsync_companion import site as site_mod

    got = site_mod.normalise({"schema": site_mod.SCHEMA, "sftp_hostkey": f"  {KEY} "})
    assert got["sftp_hostkey"] == KEY
    assert site_mod.normalise({"schema": site_mod.SCHEMA})["sftp_hostkey"] == ""
