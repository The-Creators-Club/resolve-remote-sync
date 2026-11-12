"""GL-06 (TrueNAS uid check) and GL-10 (SFTP window refusal), CR-364,
2026-10-07. server/ takes no source dependency on dashboard/, so the pin that
the two copies of the numbers agree reads the dashboard file as TEXT."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import check_health  # noqa: E402
import install_dashboard_app as ida  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def test_parse_and_problem():
    assert common.parse_sftp_size("64Ki") == 65536
    assert common.parse_sftp_size("255Ki") == 255 * 1024
    assert common.sftp_transport_problem("synology", "255Ki", "64")
    assert common.sftp_transport_problem("synology", "64Ki", "16") == ""
    assert common.sftp_transport_problem("synology", "", "") == ""
    assert common.sftp_transport_problem("truenas", "255Ki", "64") == ""


def test_derive_fills_blank_only_on_synology():
    assert common.derive_sftp_transport("synology", "", "") == ("64Ki", 16)
    assert common.derive_sftp_transport("truenas", "", "") == ("", 0)
    assert common.derive_sftp_transport("truenas", "255Ki", "64") == ("255Ki", 64)


def test_numbers_match_the_dashboard_copy():
    text = (REPO / "dashboard" / "src" / "ccsync_dashboard" / "sftp_transport.py").read_text(
        encoding="utf-8")
    assert int(re.search(r"SYNOLOGY_SAFE_CHUNK_BYTES = (\d+) \* (\d+)", text).group(1)) * \
        int(re.search(r"SYNOLOGY_SAFE_CHUNK_BYTES = (\d+) \* (\d+)", text).group(2)) == \
        common.SYNOLOGY_SAFE_SFTP_CHUNK_BYTES
    assert int(re.search(r"SYNOLOGY_SAFE_CONCURRENCY = (\d+)", text).group(1)) == \
        common.SYNOLOGY_SAFE_SFTP_CONCURRENCY


def _site(monkeypatch, values):
    monkeypatch.setattr(ida, "site_value", lambda s, k, d="": values.get((s, k), d))


def test_deploy_env_derives_safe_pair_on_synology(monkeypatch):
    _site(monkeypatch, {})
    monkeypatch.setattr(ida, "deploy_nas_kind", lambda: "synology")
    env = ida.site_env()
    assert env["DASH_SITE_SFTP_CHUNK_SIZE"] == "64Ki"
    assert env["DASH_SITE_SFTP_CONCURRENCY"] == "16"


def test_deploy_env_leaves_truenas_alone(monkeypatch):
    _site(monkeypatch, {("net", "sftp_chunk_size"): "255Ki", ("net", "sftp_concurrency"): "64"})
    monkeypatch.setattr(ida, "deploy_nas_kind", lambda: "truenas")
    env = ida.site_env()
    assert env["DASH_SITE_SFTP_CHUNK_SIZE"] == "255Ki"
    assert env["DASH_SITE_SFTP_CONCURRENCY"] == "64"


def test_deploy_refuses_the_unsafe_template_value(monkeypatch):
    _site(monkeypatch, {("net", "sftp_chunk_size"): "255Ki", ("net", "sftp_concurrency"): "64"})
    monkeypatch.setattr(ida, "deploy_nas_kind", lambda: "synology")
    assert "64Ki" in ida.sftp_transport_refusal()
    monkeypatch.setattr(ida, "deploy_nas_kind", lambda: "truenas")
    assert ida.sftp_transport_refusal() == ""


def test_check_health_fails_on_unsafe_synology_site(monkeypatch):
    class _B:
        kind = "synology"

    monkeypatch.setattr(check_health, "backend", lambda: _B())
    monkeypatch.setattr(check_health, "site_value",
                        lambda s, k, d="": {"sftp_chunk_size": "255Ki"}.get(k, d))
    check_health.RESULTS.clear()
    check_health.check_sftp_transport(False)
    assert check_health.RESULTS and check_health.RESULTS[-1][0] is False
    check_health.RESULTS.clear()


def test_truenas_identity_mismatch_is_refused(monkeypatch):
    monkeypatch.setattr(ida, "run_ssh", lambda cmd, dry_run=False, timeout=120: (0, "1000\n1001\n", ""))
    msg = ida.truenas_identity_mismatch(3000, 3001)
    assert "uid = 1000" in msg and "gid = 1001" in msg


def test_truenas_identity_match_and_unreadable_pass(monkeypatch):
    monkeypatch.setattr(ida, "run_ssh", lambda cmd, dry_run=False, timeout=120: (0, "3000\n3001\n", ""))
    assert ida.truenas_identity_mismatch(3000, 3001) == ""
    monkeypatch.setattr(ida, "run_ssh", lambda cmd, dry_run=False, timeout=120: (0, "", ""))
    assert ida.truenas_identity_mismatch(3000, 3001) == ""
    assert ida.truenas_identity_mismatch(1, 2, dry_run=True) == ""


# ---------------------------------------------------------------------------
# ops-server-2 (audit 2026-11-10): a check that cannot run is a failed check
# ---------------------------------------------------------------------------


def test_a_check_that_raises_is_one_failed_check_and_the_rest_still_run(monkeypatch, capsys):
    """With the NAS unreachable the run ended in a traceback after the first
    check and exited 1, which by the script's contract (exit code = number of
    failed checks) read as "one check failed" while five never ran."""
    monkeypatch.setattr(check_health, "RESULTS", [])

    def unreachable(dry_run):
        raise ConnectionError("Unable to connect to port 22 on 192.0.2.1")

    def fine(dry_run):
        check_health.report(True, "the next check ran")

    check_health.run_check("project tree", unreachable, False)
    check_health.run_check("dashboard", fine, False)
    out = capsys.readouterr().out
    assert check_health.RESULTS[0][0] is False
    assert "project tree: the check could not run (ConnectionError: Unable to connect" in check_health.RESULTS[0][1]
    assert check_health.RESULTS[1] == (True, "the next check ran")
    assert "FAIL: project tree" in out and "PASS: the next check ran" in out


def test_a_missing_environment_is_still_cli_s_to_report(monkeypatch):
    monkeypatch.setattr(check_health, "RESULTS", [])

    def no_env(dry_run):
        raise common.EnvError("TRUENAS_PW is not set")

    with pytest.raises(common.EnvError):
        check_health.run_check("postgres", no_env, False)
    assert check_health.RESULTS == []


# ---------------------------------------------------------------------------
# ops-server-4 (audit 2026-11-10): a secret typed on the command line is said so
# ---------------------------------------------------------------------------


def test_a_secret_on_the_command_line_is_warned_about_and_still_works(capsys):
    import common as C
    assert C.warn_secret_on_argv("--api-key", "SYNCTHING_API_KEY", ["--gui-url", "http://nas:8384"]) is False
    assert capsys.readouterr().err == ""
    assert C.warn_secret_on_argv("--api-key", "SYNCTHING_API_KEY", ["--api-key", "abc"]) is True
    err = capsys.readouterr().err
    assert "WARNING" in err and "SYNCTHING_API_KEY" in err and "abc" not in err      # never the value itself
    assert C.warn_secret_on_argv("--api-key", "SYNCTHING_API_KEY", ["--api-key=abc"]) is True
    assert "abc" not in capsys.readouterr().err
    # a flag that only starts the same way is not it
    assert C.warn_secret_on_argv("--api-key", "SYNCTHING_API_KEY", ["--api-key-file", "x"]) is False
