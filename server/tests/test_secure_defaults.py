"""The secure defaults a NEW site inherits, and the explicit legacy the studio
keeps (GL-18 / GL-19 / COM-H15, CR-368, 2026-10-07).

The fixture site (fixtures/site.toml) IS the studio's legacy manifest: it names
every legacy posture. Each test that wants a NEW site's defaults removes the
relevant keys with `_site(monkeypatch, ...)`.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import http.server
import ssl
import threading

import pytest

import common
import create_api_key
import install_dashboard_app as ida


def _site(monkeypatch, drop=(), **sections):
    """Replace the loaded manifest: remove ("section", "key") pairs in `drop`,
    then merge `sections` ({"nas": {"verify_ssl": "..."}}) over it."""
    data = copy.deepcopy(common.load_site())
    for section, key in drop:
        data.get(section, {}).pop(key, None)
    for section, values in sections.items():
        data.setdefault(section, {}).update(values)
    monkeypatch.setattr(common, "_SITE", data)
    return data


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    # each test records into its own files (conftest points them at one shared dir)
    monkeypatch.setenv("CCSYNC_KNOWN_HOSTS", str(tmp_path / "known_hosts"))
    monkeypatch.setenv("CCSYNC_KNOWN_CERTS", str(tmp_path / "known_certs.json"))
    for name in ("TRUENAS_VERIFY_SSL", "SYNO_VERIFY_SSL", "CCSYNC_SSH_TRUST_ON_FIRST_USE",
                 "CCSYNC_SSH_HOSTKEY", "PG_PASSWORD", "TRUENAS_API_KEY", "DASH_ADMIN_USERS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(common, "_TLS_WARNED", set())
    monkeypatch.setattr(common, "_HOST_KEY_PIN", "")
    monkeypatch.setattr(common, "_TRUST_ON_FIRST_USE", False)


# ------------------------------------------------------------ project ACL

def test_an_unset_project_acl_is_per_project_and_an_explicit_shared_is_kept(monkeypatch):
    _site(monkeypatch, drop=[("stack", "project_acl")])
    assert common.project_acl_mode() == "per-project"
    _site(monkeypatch, stack={"project_acl": "shared"})
    assert common.project_acl_mode() == "shared"
    # the fixture (the studio's legacy manifest) names it, so the studio is unchanged
    monkeypatch.undo()
    assert common.project_acl_mode() == "shared"


def test_a_garbage_project_acl_is_still_refused(monkeypatch):
    _site(monkeypatch, stack={"project_acl": "everyone"})
    with pytest.raises(common.EnvError):
        common.project_acl_mode()


# --------------------------------------------------------- [security] flags

def test_legacy_flags_default_off_and_unknown_flags_are_a_bug(monkeypatch):
    _site(monkeypatch, drop=[("security", k) for k in common.SECURITY_LEGACY_FLAGS])
    assert [common.security_legacy(f) for f in common.SECURITY_LEGACY_FLAGS] == [False] * 3
    with pytest.raises(KeyError):
        common.security_legacy("make_it_insecure")


def test_the_fixture_site_is_the_studios_legacy():
    assert all(common.security_legacy(f) for f in common.SECURITY_LEGACY_FLAGS)


# ----------------------------------------- COM-H5: API key, admin separation

def test_truenas_needs_an_api_key_unless_the_site_names_the_legacy(monkeypatch):
    _site(monkeypatch, drop=[("security", "allow_nas_password_in_container")])
    with pytest.raises(common.EnvError, match="TRUENAS_API_KEY"):
        ida.require_nas_api_key("truenas", "")
    ida.require_nas_api_key("truenas", "1-abc")           # a key is the answer
    ida.require_nas_api_key("synology", "")                # DSM has no such concept
    _site(monkeypatch, security={"allow_nas_password_in_container": True})
    ida.require_nas_api_key("truenas", "")                 # the studio's legacy


def test_the_dashboard_admin_must_be_named_and_must_not_be_the_nas_admin(monkeypatch):
    _site(monkeypatch, drop=[("security", "allow_nas_admin_as_dashboard_admin")])
    with pytest.raises(common.EnvError, match="DASH_ADMIN_USERS is not set"):
        ida.resolve_dashboard_admins("", "truenas_admin")
    with pytest.raises(common.EnvError, match="NAS admin account"):
        ida.resolve_dashboard_admins("alex, TrueNAS_Admin", "truenas_admin")
    assert ida.resolve_dashboard_admins("alex, sam", "truenas_admin") == "alex,sam"
    _site(monkeypatch, security={"allow_nas_admin_as_dashboard_admin": True})
    assert ida.resolve_dashboard_admins("", "truenas_admin") == "truenas_admin"
    assert ida.resolve_dashboard_admins("truenas_admin", "truenas_admin") == "truenas_admin"


def test_a_scoped_key_is_refused_for_the_admin_account_unless_asked_for():
    refusal = create_api_key.admin_key_refusal
    assert "--username is required" in refusal("", "truenas_admin", False)
    assert "NAS admin account" in refusal("TrueNAS_Admin", "truenas_admin", False)
    assert refusal("ccsync-api", "truenas_admin", False) == ""
    assert refusal("", "truenas_admin", True) == ""        # --allow-admin-key
    assert refusal("", "truenas_admin", False, shape="allowlist") == ""
    assert "ACCOUNT_WRITE" in create_api_key.RESIDUAL_RISK


# ------------------------------------------------------------- NAS TLS pin

PIN = "sha256:" + "ab" * 32


def test_a_cert_pin_is_normalised_and_a_malformed_one_is_never_off():
    assert common.parse_cert_pin("SHA256:" + ":".join(["AB"] * 32)) == "ab" * 32
    assert common.parse_cert_pin("/etc/ssl/ca.pem") == ""
    with pytest.raises(common.EnvError, match="64 hex"):
        common.parse_cert_pin("sha256:abc")
    with pytest.raises(common.EnvError):
        common._verify_ssl_setting("sha256:zz" + "0" * 62, "TRUENAS_VERIFY_SSL")


def test_the_explicit_settings_keep_their_old_meaning(monkeypatch, capsys):
    assert common._verify_ssl_setting("0", "TRUENAS_VERIFY_SSL") is False
    assert "OFF" in capsys.readouterr().err                # still loud
    assert common._verify_ssl_setting("1", "TRUENAS_VERIFY_SSL") is True
    assert common._verify_ssl_setting("/certs/ca.pem", "X") == "/certs/ca.pem"
    assert common._verify_ssl_setting(PIN.upper(), "X") == PIN


def test_unset_verification_is_refused_until_the_cert_is_recorded(monkeypatch):
    _site(monkeypatch, drop=[("nas", "verify_ssl")])
    assert common.truenas_verify_ssl.__name__ == "truenas_verify_ssl"
    with pytest.raises(common.EnvError, match="neither pinned nor recorded"):
        common.truenas_verify_ssl()


def test_trust_on_first_use_records_the_fingerprint_and_later_runs_reuse_it(
        monkeypatch, capsys):
    _site(monkeypatch, drop=[("nas", "verify_ssl")])
    monkeypatch.setenv("CCSYNC_SSH_TRUST_ON_FIRST_USE", "1")
    calls = []

    def fetch(host, port):
        calls.append((host, port))
        return "cd" * 32

    first = common.default_cert_pin("nas.example", 443, fetch=fetch)
    assert first == "sha256:" + "cd" * 32 and calls == [("nas.example", 443)]
    assert 'verify_ssl = "sha256:' in capsys.readouterr().err
    # recorded: no second handshake, and no first-use opt-in is needed any more
    monkeypatch.delenv("CCSYNC_SSH_TRUST_ON_FIRST_USE")
    assert common.default_cert_pin("nas.example", 443, fetch=fetch) == first
    assert len(calls) == 1
    # another host / port is a different record
    with pytest.raises(common.EnvError):
        common.default_cert_pin("nas.example", 5001, fetch=fetch)


def test_synology_pins_the_dsm_port(monkeypatch):
    _site(monkeypatch, drop=[("nas", "verify_ssl")], nas={"kind": "synology"})
    assert common.nas_cert_port() == common.synology_port()


def _self_signed(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nas.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "c.pem", tmp_path / "k.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return (str(cert_path), str(key_path),
            hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest())


@pytest.fixture()
def tls_server(tmp_path):
    pytest.importorskip("cryptography")
    cert, key, fp = _self_signed(tmp_path)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], fp
    server.shutdown()


def test_requests_with_verify_accepts_only_the_pinned_certificate(tls_server):
    import requests

    port, fp = tls_server
    url = f"https://127.0.0.1:{port}/"
    assert common.requests_with_verify("GET", url, "sha256:" + fp, timeout=10).text == "ok"
    with pytest.raises(requests.exceptions.SSLError):
        common.requests_with_verify("GET", url, "sha256:" + "0" * 64, timeout=10)
    with pytest.raises(requests.exceptions.SSLError):      # not in any CA bundle
        common.requests_with_verify("GET", url, True, timeout=10)


def test_fetch_cert_fingerprint_reads_what_the_server_presents(tls_server):
    port, fp = tls_server
    assert common.fetch_cert_fingerprint("127.0.0.1", port) == fp


def test_the_container_gets_the_configured_value_or_a_pin(monkeypatch):
    # configured: passes through untouched (the studio's "0" stays "0")
    assert ida.container_verify_ssl(False) == "0"
    _site(monkeypatch, drop=[("nas", "verify_ssl")])
    # a dry run never connects
    assert ida.container_verify_ssl(True) == "sha256:<recorded-at-deploy>"
    # a real run with nothing recorded is a refusal ...
    with pytest.raises(common.EnvError):
        ida.container_verify_ssl(False)
    # ... and with the cert recorded it is that pin
    common._record_known_cert("192.168.0.10", 443, "ef" * 32)
    assert ida.container_verify_ssl(False) == "sha256:" + "ef" * 32
    assert ida.container_verify_ssl(True) == "sha256:" + "ef" * 32
    # the environment beats the manifest
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "1")
    assert ida.container_verify_ssl(False) == "1"


def test_compose_config_carries_the_chosen_verify_value_and_defaults_to_the_site(monkeypatch):
    env = ida.compose_config(8480, "/root", "http://gui:8384", "k", "t",
                             truenas_verify_ssl=PIN)["services"]["dashboard"]["environment"]
    assert env["TRUENAS_VERIFY_SSL"] == PIN
    env = ida.compose_config(8480, "/root", "http://gui:8384", "k", "t"
                             )["services"]["dashboard"]["environment"]
    assert env["TRUENAS_VERIFY_SSL"] == "0"                # the fixture's own legacy
    _site(monkeypatch, drop=[("nas", "verify_ssl")])
    env = ida.compose_config(8480, "/root", "http://gui:8384", "k", "t"
                             )["services"]["dashboard"]["environment"]
    assert env["TRUENAS_VERIFY_SSL"] == ""                 # the container then verifies


# -------------------------------------------------- editor-lane host key pin

def _hostkey_line():
    paramiko = pytest.importorskip("paramiko")
    key = paramiko.ECDSAKey.generate()
    return key, f"{key.get_name()} {key.get_base64()}"


def test_the_nas_host_key_line_comes_from_the_pin_then_the_recorded_key(monkeypatch, tmp_path):
    key, line = _hostkey_line()
    assert common.nas_ssh_hostkey_line() == ""             # nothing pinned, nothing recorded
    # a pin written with a comment or a host field is normalised to "<type> <b64>"
    monkeypatch.setattr(common, "_HOST_KEY_PIN", f"nas.example {line} comment")
    assert common.nas_ssh_hostkey_line() == line
    # no pin: the key the toolchain recorded for the host
    monkeypatch.setattr(common, "_HOST_KEY_PIN", "")
    _site(monkeypatch, nas={"ssh_hostkey": ""})
    common._record_host_key("192.168.0.10", key)
    assert common.nas_ssh_hostkey_line() == line
    # a pin that cannot be parsed is returned as written, never dropped
    monkeypatch.setattr(common, "_HOST_KEY_PIN", "garbage pin")
    assert common.nas_ssh_hostkey_line() == "garbage pin"


def test_the_manifest_publishes_the_host_key_unless_the_site_skips_the_pin(monkeypatch):
    _, line = _hostkey_line()
    monkeypatch.setattr(common, "_HOST_KEY_PIN", line)
    # the studio's fixture skips the pin: its editors' rclone remotes predate it
    assert ida.site_env()["DASH_SITE_SFTP_HOSTKEY"] == ""
    _site(monkeypatch, drop=[("security", "skip_lane_host_key_pin")])
    assert ida.site_env()["DASH_SITE_SFTP_HOSTKEY"] == line
    # the pasted compose FILE renders the same value as the POSTed dict
    rendered = ida.render_compose_yaml(ida.compose_variables())
    assert f'DASH_SITE_SFTP_HOSTKEY: "{line}"' in rendered


def test_the_container_ssh_pin_falls_back_to_the_recorded_key(monkeypatch):
    key, line = _hostkey_line()
    monkeypatch.setattr(common, "_HOST_KEY_PIN", "")
    _site(monkeypatch, nas={"ssh_hostkey": ""})
    common._record_host_key("192.168.0.10", key)
    assert ida.compose_variables()["NAS_SSH_HOSTKEY"] == line


# ----------------------------------------------------------- Postgres profile

def test_the_postgres_service_has_no_default_password_and_binds_two_addresses():
    text = ida.render_compose_yaml(ida.compose_variables())
    start = text.index("  postgres:")
    block = text[start:]
    assert "DaVinci}" not in block and ":-DaVinci" not in block
    assert 'POSTGRES_PASSWORD: "${PG_PASSWORD:-}"' in block
    assert "${DASH_BIND_LAN:-192.168.0.10}:${DASH_PG_PORT:-5432}:5432" in block
    assert "${DASH_BIND_TAILNET:-100.64.0.1}:${DASH_PG_PORT:-5432}:5432" in block
    assert '- "${DASH_PG_PORT:-5432}:5432"' not in block   # the old every-interface bind
    # the refusal: empty or Resolve's default never starts
    assert 'case "$$POSTGRES_PASSWORD" in ""|DaVinci|davinci)' in block


def test_the_image_compose_file_matches(monkeypatch):
    text = ida.render_compose_yaml(ida.compose_variables(), template=ida.IMAGE_COMPOSE_TEMPLATE)
    block = text[text.index("  postgres:"):]
    assert ":-DaVinci" not in block and "${PG_PASSWORD:-}" in block
    assert "${DASH_BIND_TAILNET:-100.64.0.1}:${DASH_PG_PORT:-5432}:5432" in block


def test_a_random_project_server_password_is_made_once_and_reused(tmp_path, monkeypatch):
    monkeypatch.setenv("CCSYNC_PG_PASSWORD_FILE", str(tmp_path / "pg"))
    first = common.project_server_password()
    assert len(first) >= 24 and first.lower() != "davinci"
    assert common.project_server_password() == first       # a redeploy re-renders the same
    assert (tmp_path / "pg").read_text().strip() == first


def test_resolves_well_known_password_is_refused_from_every_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CCSYNC_PG_PASSWORD_FILE", str(tmp_path / "pg"))
    monkeypatch.setenv("PG_PASSWORD", "DaVinci")
    with pytest.raises(common.EnvError, match="well-known"):
        common.project_server_password()
    monkeypatch.delenv("PG_PASSWORD")
    (tmp_path / "pg").write_text("davinci\n")
    with pytest.raises(common.EnvError, match="well-known"):
        common.project_server_password()
    monkeypatch.setenv("PG_PASSWORD", "my-own-long-password")
    assert common.project_server_password() == "my-own-long-password"


# ------------------------------------------------- the whole deploy, dry-run

def _dry_run(monkeypatch):
    import sys

    monkeypatch.setattr(ida, "run_ssh", lambda cmd, dry_run=False, timeout=120: (0, "", ""))
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run"])
    return ida.main()


def test_a_new_truenas_site_without_an_api_key_is_refused_before_anything_runs(
        monkeypatch, capsys):
    _site(monkeypatch, drop=[("security", "allow_nas_password_in_container")])
    assert _dry_run(monkeypatch) == 1
    err = capsys.readouterr().err
    assert "FAILED" in err and "TRUENAS_API_KEY" in err and "--username" in err


def test_a_new_site_with_a_key_still_needs_a_dashboard_admin(monkeypatch, capsys):
    _site(monkeypatch, drop=[("security", "allow_nas_password_in_container"),
                             ("security", "allow_nas_admin_as_dashboard_admin")])
    monkeypatch.setenv("TRUENAS_API_KEY", "1-fakekey")
    assert _dry_run(monkeypatch) == 1
    assert "DASH_ADMIN_USERS is not set" in capsys.readouterr().err
    monkeypatch.setenv("DASH_ADMIN_USERS", "truenas_admin")
    assert _dry_run(monkeypatch) == 1
    assert "NAS admin account" in capsys.readouterr().err


def test_a_fully_secure_new_site_deploys_with_a_pin_and_no_password(monkeypatch, capsys):
    _site(monkeypatch, drop=[("security", k) for k in common.SECURITY_LEGACY_FLAGS]
          + [("nas", "verify_ssl"), ("stack", "project_acl")])
    monkeypatch.setenv("TRUENAS_API_KEY", "1-fakekey")
    monkeypatch.setenv("DASH_ADMIN_USERS", "alex")
    common._record_known_cert("192.168.0.10", 443, "12" * 32)
    assert _dry_run(monkeypatch) == 0
    out = capsys.readouterr()
    assert "TRUENAS_VERIFY_SSL" in out.out and "sha256:" + "12" * 32 in out.out
    assert "alex" in out.out
    # per-project is the new-site default and the operator is told what that means
    assert "project_acl is per-project" in out.err and "setup_editor_account.py" in out.err
    # the studio's explicit "shared" says nothing of the kind


def test_the_studios_own_legacy_manifest_deploys_exactly_as_before(monkeypatch, capsys):
    """The fixture names every legacy posture: no key, NAS admin as dashboard
    admin, verification off. The dry run must still succeed and say so."""
    assert _dry_run(monkeypatch) == 0
    out = capsys.readouterr()
    assert "TLS verification is OFF" in out.err
    assert "allow_nas_password_in_container" in out.err
    assert "project_acl is per-project" not in out.err


# ---------------------------------------------------------- the tailnet policy

def _tailnet_policy():
    import json
    import re
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[2] / "docs" / "TAILNET_POLICY.md").read_text(
        encoding="utf-8")
    block = doc.split("## The policy", 1)[1].split("```jsonc", 1)[1].split("```", 1)[0]
    lines = [ln for ln in block.splitlines() if not ln.strip().startswith("//")]
    text = re.sub(r",(\s*[}\]])", r"\1", "\n".join(lines))   # HuJSON trailing commas
    return json.loads(text)


def test_the_tailnet_policy_template_parses_and_grants_editors_exactly_the_service_ports():
    policy = _tailnet_policy()
    editor = next(g for g in policy["grants"] if g["src"] == ["tag:ccsync-editor"])
    assert editor["dst"] == ["tag:ccsync-server"]
    # what the product needs: dashboard, sftp, syncthing (tcp+udp), smb
    assert set(editor["ip"]) == {"tcp:8480", "tcp:22", "tcp:22000", "udp:22000", "tcp:445"}
    # and not what it must not have
    assert not {"tcp:5432", "tcp:5001", "tcp:8384"} & set(editor["ip"])


def test_the_tailnet_policy_has_no_wildcard_rule_and_tests_that_pin_it():
    policy = _tailnet_policy()
    for grant in policy["grants"]:
        assert "*" not in grant["src"] and "*" not in grant["dst"]
        assert "*" not in grant["ip"]
    assert "acls" not in policy, "the legacy allow-all section must not come back"
    denied = {d for t in policy["tests"] for d in t.get("deny", [])}
    assert {"tag:ccsync-server:5432", "tag:ccsync-editor:22"} <= denied
    # no editor-to-editor grant
    assert not any(g["src"] == ["tag:ccsync-editor"] and "tag:ccsync-editor" in g["dst"]
                   for g in policy["grants"])


def test_the_policy_ports_match_the_defaults_this_repo_deploys():
    assert ida.DEFAULT_PORT == 8480 if hasattr(ida, "DEFAULT_PORT") else True
    text = ida.render_compose_yaml(ida.compose_variables())
    assert "22000:22000/tcp" in text and "22000:22000/udp" in text
    # the Syncthing GUI is loopback only, so the policy never grants 8384
    assert '"127.0.0.1:8384:8384"' in text


def _pg_script(template):
    import re
    text = ida.render_compose_yaml(ida.compose_variables(), template=template)
    block = text[text.index("  postgres:"):]
    m = re.search(r"      - \|\n((?:        .*\n)+)", block)
    assert m, "the postgres command must be a block scalar"
    return "\n".join(ln[8:] for ln in m.group(1).splitlines())


@pytest.mark.parametrize("template", [None, "image"])
def test_an_initialised_postgres_volume_is_rekeyed_before_the_server_starts(template):
    """CR-368 follow-up (2026-10-07): initdb reads POSTGRES_PASSWORD only on an
    empty volume, so a cluster started under 'DaVinci' kept it while the deploy
    told the admin to type the new password."""
    tpl = ida.IMAGE_COMPOSE_TEMPLATE if template == "image" else ida.compose_template_for("custom")
    script = _pg_script(tpl)
    assert script.index("ALTER ROLE postgres") < script.index("exec docker-entrypoint.sh")
    assert "PG_VERSION" in script and "--single" in script
    assert "refusing to start: could not set" in script     # fatal, never a silent mismatch
    assert 'case "$$POSTGRES_PASSWORD" in ""|DaVinci|davinci)' in script


def test_the_postgres_command_script_is_valid_shell(tmp_path):
    import shutil, subprocess
    if shutil.which("bash") is None:
        pytest.skip("needs bash")
    f = tmp_path / "pg.sh"
    f.write_text(_pg_script(ida.IMAGE_COMPOSE_TEMPLATE).replace("$$", "$"), encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode == 0
