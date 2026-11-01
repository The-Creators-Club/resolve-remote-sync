"""GL-06 (container uid on Synology) and GL-10 (the SFTP window DSM's sshd
cannot serve), CR-364, 2026-10-07."""
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from ccsync_dashboard import alerts, setup_engine, sftp_transport, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.settings import Settings


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "s.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()


def _settings(tmp_path, **kw):
    return Settings(db_path=str(tmp_path / "s.db"), **kw)


# ------------------------------------------------------------------ GL-10

def test_parse_size_reads_rclone_units():
    assert sftp_transport.parse_size("64Ki") == 65536
    assert sftp_transport.parse_size("255Ki") == 255 * 1024
    assert sftp_transport.parse_size("1M") == 1024 ** 2
    assert sftp_transport.parse_size("65536") == 65536
    assert sftp_transport.parse_size("") is None
    assert sftp_transport.parse_size("lots") is None


def test_only_a_synology_site_on_dsms_sshd_is_limited():
    assert sftp_transport.problem("synology", "255Ki", 64)
    assert sftp_transport.problem("synology", "64Ki", 16) == ""
    assert sftp_transport.problem("truenas", "255Ki", 64) == ""
    # the appliance's own sidecar (OpenSSH 9.6) is fine at 255Ki
    assert sftp_transport.problem("synology", "255Ki", 64, vendor_defaults=True) == ""


def test_derive_fills_a_blank_and_lowers_an_unsafe_value():
    assert sftp_transport.derive("synology", "", 0) == ("64Ki", 16)
    assert sftp_transport.derive("synology", "255Ki", 64) == ("64Ki", 16)
    assert sftp_transport.derive("synology", "32Ki", 8) == ("32Ki", 8)
    assert sftp_transport.derive("truenas", "", 0) == ("", 0)
    assert sftp_transport.derive("truenas", "255Ki", 64) == ("255Ki", 64)


def test_manifest_serves_the_safe_pair_and_reports_the_stored_problem(conn, tmp_path):
    settings = _settings(tmp_path, nas_kind="synology",
                         site_sftp_chunk_size="255Ki", site_sftp_concurrency=64)
    m = site_store.resolved_manifest(conn, settings)
    assert (m["sftp_chunk_size"], m["sftp_concurrency"]) == ("64Ki", 16)
    assert "255Ki" in m["_sftp_transport_problem"]


def test_manifest_of_a_truenas_site_is_untouched(conn, tmp_path):
    settings = _settings(tmp_path, site_sftp_chunk_size="255Ki", site_sftp_concurrency=64)
    m = site_store.resolved_manifest(conn, settings)
    assert (m["sftp_chunk_size"], m["sftp_concurrency"]) == ("255Ki", 64)
    assert m["_sftp_transport_problem"] == ""


def test_settings_save_refuses_a_big_chunk_on_synology(conn, tmp_path):
    settings = _settings(tmp_path, nas_kind="synology")
    with pytest.raises(site_store.SiteValidationError):
        site_store.set_many(conn, {"sftp_chunk_size": "255Ki"}, "owen", settings=settings)
    site_store.set_many(conn, {"sftp_chunk_size": "64Ki", "sftp_concurrency": "16"},
                        "owen", settings=settings)


def test_switching_the_kind_to_synology_is_judged_against_the_stored_chunk(conn, tmp_path):
    settings = _settings(tmp_path)
    site_store.set_many(conn, {"sftp_chunk_size": "255Ki"}, "owen", settings=settings)
    with pytest.raises(site_store.SiteValidationError):
        site_store.set_many(conn, {"nas_kind": "synology"}, "owen", settings=settings)


def test_unrelated_save_on_an_old_bad_row_still_goes_through(conn, tmp_path):
    settings = _settings(tmp_path, nas_kind="synology",
                         site_sftp_chunk_size="255Ki", site_sftp_concurrency=64)
    site_store.set_many(conn, {"org_name": "Studio"}, "owen", settings=settings)


def test_alert_fires_on_an_unsafe_stored_window(conn, tmp_path):
    settings = _settings(tmp_path, nas_kind="synology",
                         site_sftp_chunk_size="255Ki", site_sftp_concurrency=64)
    kind = alerts.KIND_BY_NAME["sftp_transport_unsafe"]
    assert kind.kind in {k for _g, names in alerts.KIND_GROUPS for k in names}
    ctx = alerts.Ctx(conn, settings, "2026-10-07T12:00:00+00:00")
    found = kind.check(ctx)
    assert len(found) == 1
    ok_settings = _settings(tmp_path, nas_kind="synology",
                            site_sftp_chunk_size="64Ki", site_sftp_concurrency=16)
    assert kind.check(alerts.Ctx(conn, ok_settings, "2026-10-07T12:00:00+00:00")) == []


def test_site_example_does_not_ship_the_unsafe_value():
    text = (Path(__file__).resolve().parents[2] / "site.example.toml").read_text(
        encoding="utf-8")
    live = [ln for ln in text.splitlines()
            if ln.strip().startswith(("sftp_chunk_size", "sftp_concurrency"))]
    assert live == []


# ------------------------------------------------------------------ GL-06

def test_probe_failure_names_the_account_and_app_uid(tmp_path):
    exc = PermissionError(errno.EACCES, "Permission denied")
    hint = setup_engine.storage_identity_hint(tmp_path, exc)
    assert "APP_UID" in hint and "APP_GID" in hint
    assert "id <account>" in hint


def test_a_full_disk_is_not_blamed_on_ownership(tmp_path):
    assert setup_engine.storage_identity_hint(
        tmp_path, OSError(errno.ENOSPC, "No space left")) == ""


def test_run_storage_failure_carries_the_cause(tmp_path, monkeypatch, conn):
    settings = _settings(tmp_path, projects_dir=str(tmp_path))

    def boom(self, *a, **k):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "write_text", boom)

    class _App:
        class state:                                               # noqa: N801
            pass

    ctx = setup_engine.SetupContext(conn=conn, settings=settings, app=_App())
    state = setup_engine._run_storage(ctx)
    assert state.status == "fail"
    assert "APP_UID" in state.detail


def test_compose_no_longer_promises_a_writeback():
    text = (Path(__file__).resolve().parents[1] / "deploy" / "compose.appliance.yaml"
            ).read_text(encoding="utf-8")
    assert "writes it\n# back" not in text.replace("\r\n", "\n")
    assert "NOTHING writes these two variables back" in text


# ------------------------------------------------- CR-364 overseer follow-ups

def test_boot_seed_is_not_vetoed_by_an_old_deploys_unsafe_chunk(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_SITE_ORG_NAME", "Studio")
    settings = _settings(tmp_path, nas_kind="synology", site_org_name="Studio",
                         site_sftp_chunk_size="255Ki", site_sftp_concurrency=64)
    assert site_store._seed_from_env_once(conn, settings) is True
    assert site_store.get_all(conn)["org_name"] == "Studio"
    m = site_store.resolved_manifest(conn, settings)
    assert (m["sftp_chunk_size"], m["sftp_concurrency"]) == ("64Ki", 16)


def test_chunk_size_hint_no_longer_suggests_64m():
    html = (Path(__file__).resolve().parents[1] / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    assert "Example: 64M" not in html
    assert "64Ki" in html and "_sftp_transport_problem" in html


def test_sidecar_entrypoint_tolerates_a_gid_alpine_already_owns():
    # Alpine's /etc/group owns gid 100 (users); DSM's default primary gid is 100.
    sh = (Path(__file__).resolve().parents[1] / "deploy" / "sftp" / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'groupmod -n editors "$OWNER"' in sh
    assert "groupadd -o" not in sh
    assert "addgroup -g" not in sh.replace("BusyBox addgroup", "")


def _run_group_block(tmp_path, app_gid, runs=1, allow_fail=False):
    """Run the entrypoint's real `editors` block over a fake /etc/group and
    return getgrgid()'s answer the way sshd resolves it: first row wins."""
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    sh = (Path(__file__).resolve().parents[1] / "deploy" / "sftp" / "entrypoint.sh").read_text(encoding="utf-8")
    start = sh.index('APP_GID="${APP_GID:-3001}"')
    end = sh.index("# One synchronous pass")
    block = sh[start:end]
    grp = tmp_path / "group"
    grp.write_text("root:x:0:root\nsshd:x:22:\nusers:x:100:games\nsftpkeys:x:1000:\nnogroup:x:65533:\n", encoding="utf-8", newline="\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stubs = {
        "getent": 'if [ "$1" != group ]; then exit 2; fi\n'
                  'awk -F: -v k="$2" \'$1==k || $3==k {print; found=1} END{exit !found}\' "$GROUPFILE"\n',
        "groupmod": 'sed "s/^$3:/$2:/" "$GROUPFILE" > "$GROUPFILE.n" && mv "$GROUPFILE.n" "$GROUPFILE"\n',
        "groupadd": 'echo "$3:x:$2:" >> "$GROUPFILE"\n',
    }
    for name, body in stubs.items():
        f = bindir / name
        f.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
        f.chmod(0o755)
    script = tmp_path / "block.sh"
    script.write_text("set -eu\n" + block, encoding="utf-8", newline="\n")
    env = dict(os.environ, GROUPFILE=grp.as_posix(), APP_GID=str(app_gid),
               PATH=bindir.as_posix() + ":" + os.environ["PATH"])
    for _ in range(runs):
        r = subprocess.run([bash, script.as_posix()], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            if not allow_fail:
                raise AssertionError(r.stderr)
            return None, r.stderr
    first = {}
    text = grp.read_text(encoding="utf-8")
    for line in text.splitlines():
        name, _, gid, _ = line.split(":")
        first.setdefault(gid, name)
    return first, text


def test_editors_is_the_name_sshd_resolves_for_a_gid_alpine_owns(tmp_path):
    first, text = _run_group_block(tmp_path, 100)
    assert first["100"] == "editors", text


def test_restart_runs_the_block_again_without_harm(tmp_path):
    first, text = _run_group_block(tmp_path, 100, runs=2)
    assert first["100"] == "editors" and "sftpkeys:x:1000:" in text


@pytest.mark.parametrize("gid,name", [(1000, "sftpkeys"), (0, "root"), (22, "sshd")])
def test_a_group_the_image_uses_by_name_is_never_renamed(tmp_path, gid, name):
    first, err = _run_group_block(tmp_path, gid, allow_fail=True)
    assert first is None and name in err and "APP_GID" in err
    assert f"{name}:x:{gid}:" in (tmp_path / "group").read_text(encoding="utf-8")


def test_editors_group_is_created_for_a_free_gid(tmp_path):
    first, text = _run_group_block(tmp_path, 3001)
    assert first["3001"] == "editors", text
