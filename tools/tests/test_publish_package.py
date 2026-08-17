r"""tools/publish_package.py -- publish-only path for prebuilt artefacts
(ZERO_TOUCH_PLAN.md WP E, 2026-08-17).

Same venv and invocation as test_sign_release.py. Every test points
CCSYNC_RELEASE_KEY at a tmp key; no network -- the transport is a fake that
records what would have been sent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import publish_package as pp  # noqa: E402
import release_key as release_key_mod  # noqa: E402
from ccsync_companion import release_pubkey  # noqa: E402

URL = "http://dash.example:8480"


@pytest.fixture
def key(tmp_path, monkeypatch):
    path = tmp_path / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(path))
    assert release_key_mod.main(["new"]) == 0
    return path


@pytest.fixture
def artifact(tmp_path):
    p = tmp_path / "ccsync-companion"
    p.write_bytes(b"\xcf\xfa\xed\xfe" + b"x" * 5000)
    return p


class FakeHttp:
    """Scripted responses keyed by (method, path-without-query)."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def send(self, method, url, headers=None, body=None, timeout=None):
        path = url.split("?", 1)[0].replace(URL, "")
        self.calls.append((method, url, dict(headers or {}), body))
        status, payload = self.script.get((method, path), (500, {"detail": "unscripted"}))
        return pp.Response(status, {}, json.dumps(payload).encode())


def _pw(_stdin, _prompt):
    return "correct horse battery"


def base_argv(artifact):
    return ["--artifact", str(artifact), "--platform", "macos", "--version", "0.8.0",
            "--dashboard-url", URL, "--admin-user", "owen"]


def test_password_never_an_argument_or_env():
    with pytest.raises(SystemExit):
        pp.parse_args(["--password", "x"])
    env_names = [v for n, v in vars(pp).items() if n.endswith("_ENV")]
    assert not any("PASS" in v.upper() or "PW" in v.upper() for v in env_names)


def test_dry_run_signs_and_builds_the_put_without_network(key, artifact, capsys):
    rc = pp.main(base_argv(artifact) + ["--dry-run", "--make-current"], http=None, environ={})
    assert rc == 0
    out = capsys.readouterr().out
    assert f"would PUT {URL}/api/v1/admin/packages/macos/0.8.0?kind=companion&sha256=" in out
    assert "&make_current=1&signature=" in out
    assert "&pubkey_id=" in out


def test_full_publish_flow_logs_in_puts_signed_record_and_reads_back(key, artifact, capsys):
    http = FakeHttp({
        ("GET", "/api/v1/companion/package/macos/0.8.0"): (404, {}),
        ("POST", "/api/v1/login"): (200, {"ok": True, "user": "owen", "is_admin": True}),
        ("PUT", "/api/v1/admin/packages/macos/0.8.0"): (200, {"ok": True, "view": {}}),
        ("GET", "/api/v1/admin/packages"): (200, {"packages": [
            {"kind": "companion", "platform": "macos", "version": "0.8.0", "is_current": True}]}),
    })
    rc = pp.main(base_argv(artifact) + ["--make-current"], http=http,
                 environ={"DASH_REPORT_TOKEN": "tok"}, password_reader=_pw)
    assert rc == 0, capsys.readouterr()
    methods = [c[0] for c in http.calls]
    assert methods == ["GET", "POST", "PUT", "GET"]
    # pre-flight rides the report token, one byte only
    assert http.calls[0][2]["X-CCSync-Token"] == "tok"
    assert http.calls[0][2]["Range"] == "bytes=0-0"
    # login body carries the password, argv/env never did
    assert json.loads(http.calls[1][3])["password"] == "correct horse battery"
    # the PUT: raw bytes, and a query the dashboard's verifier accepts
    put_url, put_body = http.calls[2][1], http.calls[2][3]
    assert put_body == artifact.read_bytes()
    q = dict(p.split("=", 1) for p in put_url.split("?", 1)[1].split("&"))
    assert q["kind"] == "companion" and q["make_current"] == "1"
    from urllib.parse import unquote
    record = {
        "kind": "companion", "platform": "macos", "version": "0.8.0",
        "filename": pp.sign_release.package_filename("companion", "macos", "0.8.0", head=artifact.read_bytes()[:8]),
        "sha256": q["sha256"], "size_bytes": artifact.stat().st_size,
        "min_version": unquote(q["min_version"]), "published_at": unquote(q["published_at"]),
        "signed_binary": q["signed_binary"] == "1",
    }
    import base64
    from ccsync_companion import ed25519
    secret = release_key_mod.read_secret(release_key_mod.key_path(""))
    pub = base64.b64encode(ed25519.public_key(secret)).decode("ascii")
    ok, detail = release_pubkey.verify_record(record, unquote(q["signature"]), pubkeys=[pub])
    assert ok, detail
    assert "server row:" in capsys.readouterr().out


def test_already_published_is_discovered_before_the_password_prompt(key, artifact):
    http = FakeHttp({("GET", "/api/v1/companion/package/macos/0.8.0"): (206, {})})
    asked = []

    def pw(*_a):
        asked.append(1)
        return "x"

    rc = pp.main(base_argv(artifact), http=http, environ={"DASH_REPORT_TOKEN": "tok"}, password_reader=pw)
    assert rc == pp.EXIT_ALREADY_PUBLISHED
    assert asked == []
    assert [c[0] for c in http.calls] == ["GET"]


def test_non_admin_login_refuses_and_never_puts(key, artifact):
    http = FakeHttp({("POST", "/api/v1/login"): (200, {"ok": True, "user": "ed", "is_admin": False})})
    rc = pp.main(base_argv(artifact), http=http, environ={}, password_reader=_pw)
    assert rc == pp.EXIT_LOGIN
    assert [c[0] for c in http.calls] == ["POST"]


def test_409_from_the_server_is_its_own_exit_code(key, artifact):
    http = FakeHttp({
        ("POST", "/api/v1/login"): (200, {"is_admin": True}),
        ("PUT", "/api/v1/admin/packages/macos/0.8.0"): (409, {"detail": "exists"}),
    })
    rc = pp.main(base_argv(artifact), http=http, environ={}, password_reader=_pw)
    assert rc == pp.EXIT_ALREADY_PUBLISHED


def test_manifest_fills_the_blanks_and_refuses_dirty_or_untested(key, artifact, tmp_path):
    man = artifact.parent / "ccsync-release.json"
    base = {"version": "0.8.0", "platform": "macos", "artifact": artifact.name,
            "sha256": pp.sha256_of(artifact), "signed_binary": False,
            "git_dirty": False, "tests_run": True}
    man.write_text(json.dumps(base), encoding="utf-8")
    common = ["--manifest", str(man), "--dashboard-url", URL, "--admin-user", "owen", "--dry-run"]
    assert pp.main(common, environ={}) == 0

    man.write_text(json.dumps({**base, "git_dirty": True, "version_stamp": "0.8.0+dirty"}), encoding="utf-8")
    assert pp.main(common, environ={}) == pp.EXIT_USAGE
    assert pp.main(common + ["--allow-dirty"], environ={}) == 0

    man.write_text(json.dumps({**base, "tests_run": False}), encoding="utf-8")
    assert pp.main(common, environ={}) == pp.EXIT_USAGE
    assert pp.main(common + ["--allow-untested"], environ={}) == 0

    man.write_text(json.dumps({**base, "sha256": "0" * 64}), encoding="utf-8")
    assert pp.main(common, environ={}) == pp.EXIT_USAGE  # wrong file / changed after build


def test_onboard_kind_uses_kind_query_and_zip_filename(key, tmp_path, capsys):
    zip_like = tmp_path / "onboard.zip"
    zip_like.write_bytes(b"PK\x03\x04" + b"z" * 100)
    rc = pp.main(["--artifact", str(zip_like), "--kind", "onboard", "--platform", "macos",
                 "--version", "1.0.30", "--dashboard-url", URL, "--admin-user", "owen", "--dry-run"],
                 environ={})
    assert rc == 0
    out = capsys.readouterr().out
    assert "/api/v1/admin/packages/macos/1.0.30?kind=onboard&" in out


def test_missing_key_is_a_message_not_a_login(artifact, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(tmp_path / "absent.key"))
    http = FakeHttp({})
    rc = pp.main(base_argv(artifact), http=http, environ={}, password_reader=_pw)
    assert rc == pp.EXIT_USAGE
    assert http.calls == []
    assert "release key is missing" in capsys.readouterr().err
