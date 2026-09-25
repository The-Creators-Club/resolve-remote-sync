"""Wave 2 of the 2026-09-24 hunt's fix pass, group d-ops.

Each test names its finding. They pin the fixed behaviour and fail on the
code at 4462a2a (the reason is in each docstring).
"""
from __future__ import annotations

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, ytdl
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

# The fake ytdlweb package test_ytdl_mount.py builds; reused rather than
# copied so the two never drift.
from test_ytdl_mount import _build_fake_ytdlweb

SECRET = "n" * 32
OLD_SECRET = "o" * 40


@pytest.fixture
def ytdl_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YTDL_DATA_ROOT", str(tmp_path / "ytdldata"))
    monkeypatch.setenv("YTDL_PROJECTS_ROOT", str(tmp_path / "projects"))
    for name, module in _build_fake_ytdlweb().items():
        monkeypatch.setitem(sys.modules, name, module)
    return tmp_path


def _app(tmp_path, **kw):
    kw.setdefault("site_feature_youtube_download", True)
    return create_app(Settings(db_path=str(tmp_path / "d.db"),
                               session_secret=SECRET, **kw))


# --- bug-dash-ops-2 ---------------------------------------------------------

def test_ops2_a_session_signed_with_the_previous_secret_still_names_its_owner(
        tmp_path, ytdl_env):
    """bug-dash-ops-2: after a DASH-2 rotation login_gate accepts the old
    cookie, and so must the identity stamp. HEAD re-read the cookie with the
    current secret only, so the sub-app saw {"user": None} (ytdlweb 401s)."""
    app = _app(tmp_path, session_secrets_previous=(OLD_SECRET,))
    with TestClient(app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(OLD_SECRET, "bob"))
        r = c.get("/ytdl/api/me")
        assert r.status_code == 200
        assert r.json() == {"user": "bob"}


def test_ops2_the_bare_gate_also_knows_the_previous_keys(tmp_path):
    """bug-dash-ops-2, the no-app fallback: a gate built with settings but
    driven without the dashboard around it still honours the accept-only keys."""
    seen: dict = {}

    async def spy(scope, receive, send):
        seen["headers"] = dict(scope["headers"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_m):
        return None

    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        session_secrets_previous=(OLD_SECRET,))
    gate = ytdl.YtdlGate(spy, SECRET, settings)
    cookie = auth.make_session_cookie(OLD_SECRET, "bob").encode()
    scope = {"type": "http", "method": "GET", "path": "/ytdl/api/me",
             "root_path": "/ytdl",
             "headers": [(b"cookie", b"ccsync_session=" + cookie)]}
    asyncio.run(gate(scope, receive, send))
    assert seen["headers"].get(b"x-ccsync-user") == b"bob"


# --- bug-dash-ops-3 ---------------------------------------------------------

def test_ops3_two_session_cookies_name_the_one_login_gate_authenticated(
        tmp_path, ytdl_env):
    """bug-dash-ops-3: Starlette's parser (login_gate) keeps the LAST
    ccsync_session; HEAD's gate stamped the FIRST, so the sub-app acted as a
    different person from the one the gate let in."""
    app = _app(tmp_path)
    first = auth.make_session_cookie(SECRET, "alice")
    last = auth.make_session_cookie(SECRET, "bob")
    with TestClient(app) as c:
        r = c.get("/ytdl/api/me",
                  headers={"Cookie": f"ccsync_session={first}; ccsync_session={last}"})
        assert r.json() == {"user": "bob"}


def test_ops3_the_cookie_helper_is_last_wins():
    headers = [(b"cookie", b"ccsync_session=A; x=1"),
               (b"cookie", b"ccsync_session=B")]
    assert ytdl._session_cookie(headers) == "B"


def test_ops3_the_gate_defers_to_login_gates_verdict(tmp_path):
    """bug-dash-ops-3, revocation: once login_gate has decided the session is
    NOT live (a revoked row, "log out everywhere"), the stamp must not
    resurrect it from the cookie's signature alone. HEAD ignored the verdict
    cached on the request state and stamped the cookie's owner."""
    seen: dict = {}

    async def spy(scope, receive, send):
        seen["headers"] = dict(scope["headers"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_m):
        return None

    dash = _app(tmp_path)
    gate = ytdl.YtdlGate(spy, SECRET, dash.state.settings)
    cookie = auth.make_session_cookie(SECRET, "revoked-rita").encode()
    scope = {"type": "http", "method": "GET", "path": "/ytdl/api/me",
             "root_path": "/ytdl", "app": dash,
             # what login_gate leaves behind for a revoked session
             "state": {"ccsync_session": (None, None, False)},
             "headers": [(b"cookie", b"ccsync_session=" + cookie)]}
    asyncio.run(gate(scope, receive, send))
    assert b"x-ccsync-user" not in seen["headers"]


# --- bug-dash-ops-4 ---------------------------------------------------------

from ccsync_dashboard import crash_report  # noqa: E402


@pytest.mark.parametrize("text, secret", [
    ("DASH_SESSION_SECRET=abcdef123", "abcdef123"),
    ("TRUENAS_PW=hunter2", "hunter2"),
    ("SYNCTHING_API_KEY: zzzz", "zzzz"),
    ("{'password': 'hunter2'}", "hunter2"),
    ('{"api_key": "k123"}', "k123"),
    ("DASH_SESSION_SECRET_PREVIOUS=oldsecret99", "oldsecret99"),
    ("{'password': 'two words'}", "words"),
    ("BROLL_INGEST_TOKEN=tok456", "tok456"),
])
def test_ops4_env_style_and_quoted_keys_are_redacted(text, secret):
    """bug-dash-ops-4: HEAD's `\b(token|...|pw)\b` needed a non-word char
    before the key, and `_` is a word char, so each of these came back
    unchanged (the verifier exec'd HEAD's pattern on the first five)."""
    out = crash_report.redact(text)
    assert secret not in out, out
    assert "<redacted>" in out


@pytest.mark.parametrize("text, secret", [
    ("token=abc", "abc"),
    ("POST failed: token=abcdef123456", "abcdef123456"),
    ("https://admin:hunter2@nas.example/api", "hunter2"),
    ("Authorization: Bearer abc.def-ghi", "abc.def-ghi"),
])
def test_ops4_what_was_already_redacted_still_is(text, secret):
    out = crash_report.redact(text)
    assert secret not in out, out
    assert "<redacted>" in out


def test_ops4_words_that_merely_contain_a_key_are_left_alone():
    # "keypwd" / "stoken" are not keys; the boundary is a letter or digit.
    assert crash_report.redact("stoken=1 mypw=2") == "stoken=1 mypw=2"


# --- bug-dash-ops-9 ---------------------------------------------------------

class _S:
    def __init__(self, db_path):
        self.db_path = str(db_path)


def test_ops9_two_crashes_in_one_second_on_one_thread_keep_both(tmp_path, monkeypatch):
    """bug-dash-ops-9: the name is `<second>-<thread>.json` and HEAD opened it
    O_TRUNC, so the second report of a burst overwrote the first."""
    monkeypatch.delenv("DASH_CRASH_DIR", raising=False)
    settings = _S(tmp_path / "dashboard.db")
    first = {"when": "2026-09-25T10:00:00+00:00", "thread": "ThreadPoolExecutor-0_0",
             "exception": {"message": "first, the cause"}}
    second = dict(first, exception={"message": "second, the symptom"})
    p1 = crash_report.write_report(first, settings)
    p2 = crash_report.write_report(second, settings)
    assert p1 is not None and p2 is not None and p1 != p2
    assert "first, the cause" in p1.read_text(encoding="utf-8")
    assert "second, the symptom" in p2.read_text(encoding="utf-8")
    assert len(list((tmp_path / "crashes").glob("*.json"))) == 2


# --- bug-dash-ops-8 ---------------------------------------------------------

from ccsync_dashboard import cli_tools  # noqa: E402

CLI = cli_tools.CLAUDE_CODE


def _install(settings, version):
    d = cli_tools.tool_root(settings, CLI) / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "claude").write_bytes(b"claude " + version.encode())
    cli_tools._finish_install(settings, CLI, version=version, rel="claude",
                              sha="a" * 64, size=10, url="https://x/claude",
                              checksum_source="publisher_manifest")


@pytest.fixture
def cli_settings(tmp_path):
    return Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET)


def test_ops8_a_second_update_inside_the_grace_spares_the_first_replaced_version(
        cli_settings, monkeypatch):
    """bug-dash-ops-8: A -> B, then B -> C ten minutes later. HEAD rebuilt the
    record naming only B as replaced and pruned A at once, pulling the binary
    out from under a Timeline Cards call started on A before the first flip."""
    clock = [2_000_000.0]
    monkeypatch.setattr(cli_tools.time, "time", lambda: clock[0])
    root = cli_tools.tool_root(cli_settings, CLI)
    _install(cli_settings, "2.1.100")
    _install(cli_settings, "2.1.200")               # A replaced at t0
    clock[0] += 600
    _install(cli_settings, "2.1.300")               # B replaced at t0+600
    assert (root / "2.1.100" / "claude").is_file()
    assert (root / "2.1.200" / "claude").is_file()

    t0 = 2_000_000.0
    grace = cli_tools.PRUNE_GRACE_SECONDS
    # each version goes on ITS OWN clock
    assert cli_tools.sweep_superseded(cli_settings, CLI, now=t0 + grace - 1) == ""
    assert cli_tools.sweep_superseded(cli_settings, CLI, now=t0 + grace) == "2.1.100"
    assert not (root / "2.1.100").exists()
    assert (root / "2.1.200").is_dir()
    assert cli_tools.sweep_superseded(cli_settings, CLI, now=t0 + 600 + grace) == "2.1.200"
    assert not (root / "2.1.200").exists()
    assert (root / "2.1.300" / "claude").is_file()
    state = cli_tools.read_state(cli_settings, CLI)
    assert "previous_version" not in state and "superseded_earlier" not in state


def test_ops8_the_record_keeps_the_shape_an_older_dashboard_reads(
        cli_settings, monkeypatch):
    """Skew: previous_version / superseded_at_epoch still name the NEWEST
    replaced version, so a rolled-back dashboard sweeps that one as before."""
    clock = [3_000_000.0]
    monkeypatch.setattr(cli_tools.time, "time", lambda: clock[0])
    for v in ("2.1.100", "2.1.200"):
        _install(cli_settings, v)
    clock[0] += 60
    _install(cli_settings, "2.1.300")
    state = cli_tools.read_state(cli_settings, CLI)
    assert state["previous_version"] == "2.1.200"
    assert state["superseded_at_epoch"] == 3_000_060.0
    assert state["superseded_earlier"] == [{"version": "2.1.100", "at": 3_000_000.0}]


def test_ops8_reinstalling_a_version_in_grace_does_not_list_it_as_replaced(
        cli_settings, monkeypatch):
    clock = [4_000_000.0]
    monkeypatch.setattr(cli_tools.time, "time", lambda: clock[0])
    _install(cli_settings, "2.1.100")
    _install(cli_settings, "2.1.200")
    _install(cli_settings, "2.1.100")               # back to A inside the hour
    entries = cli_tools._superseded_entries(cli_tools.read_state(cli_settings, CLI))
    assert [e["version"] for e in entries] == ["2.1.200"]


# --- logic-release-3 / logic-release-4 ----------------------------------------

import types  # noqa: E402

from ccsync_dashboard import db as dbmod  # noqa: E402
from ccsync_dashboard import dashboard_update, package_store  # noqa: E402
from ccsync_dashboard import release_feed as rf  # noqa: E402

NOW = "2026-09-25T12:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(str(tmp_path / "rel.db"))
    dbmod.migrate(c)
    yield c
    c.close()


def _comp(version, requires=""):
    r = {"kind": "companion", "platform": "windows", "version": version,
         "filename": f"ccsync-{version}.exe", "sha256": "0" * 64,
         "size_bytes": 1, "url": "https://example.invalid/x"}
    if requires:
        r["requires_dashboard"] = requires
    return r


def _dash(version, published_at="2026-01-01T00:00:00Z"):
    return {"kind": "dashboard", "platform": "linux", "version": version,
            "published_at": published_at}


def test_rel3_a_staged_companion_is_not_what_the_vendor_offers(conn):
    """logic-release-3 (a): publish_latest without --make-current leaves the
    pointer on 0.9.78. HEAD wrote 0.9.79 into feed_offered too, and invariant
    11 / the HEALTH box took its max: "the vendor offers 0.9.79"."""
    channel = {"current": {"companion/windows": "0.9.78"}}
    rf.record_offer_state(conn, [_comp("0.9.77"), _comp("0.9.78"), _comp("0.9.79")],
                          NOW, channel=channel)
    assert sorted(dbmod.get_feed_offered(conn)["windows"]) == ["0.9.77", "0.9.78"]


def test_rel3_a_pointer_moved_back_withdraws_the_build_above_it(conn):
    """logic-release-3 (b): the vendor withdraws 0.9.79 by pointing back at
    0.9.78; every customer must stop reporting 0.9.79 as offered."""
    rf.record_offer_state(conn, [_comp("0.9.78"), _comp("0.9.79")], NOW,
                          channel={"current": {"companion/windows": "0.9.79"}})
    assert "0.9.79" in dbmod.get_feed_offered(conn)["windows"]
    rf.record_offer_state(conn, [_comp("0.9.78"), _comp("0.9.79")], NOW,
                          channel={"current": {"companion/windows": "0.9.78"}})
    assert dbmod.get_feed_offered(conn)["windows"] == ["0.9.78"]


def test_rel3_a_staged_build_that_needs_a_newer_dashboard_raises_no_notice(conn):
    """The refusal notice is news only for the build that would be taken; a
    staged one is offered to nobody (HEAD raised feed_publish_refused for it)."""
    refused = rf.record_offer_state(
        conn, [_comp("0.9.78"), _comp("0.9.79", requires="99.0.0")], NOW,
        channel={"current": {"companion/windows": "0.9.78"}})
    assert refused == []
    assert not [r for r in dbmod.open_notices(conn)
                if r["kind"] == "feed_publish_refused"]


from test_release_feed import env as feed_env  # noqa: E402,F401 - a fixture


def test_rel3_a_real_check_measures_against_the_signed_pointer(feed_env, monkeypatch):
    """End to end through check_now with a signed channel: the pointer names
    0.9.1 and 0.9.2 is staged beside it. HEAD's feed_offered carried 0.9.2."""
    import json as _json
    import test_release_feed as trf

    client, c, _settings = feed_env
    rec1, body1 = trf.make_record(version="0.9.1", body=b"one")
    rec2, body2 = trf.make_record(version="0.9.2", body=b"two")
    channel, sig = trf.make_channel([rec1, rec2],
                                    current={"companion/windows": "0.9.1"})
    trf.patch_opener(monkeypatch, {
        trf.CHANNEL_URL: _json.dumps(channel).encode(), trf.SIG_URL: sig.encode(),
        rec1["url"]: body1, rec2["url"]: body2})
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    assert dbmod.get_feed_offered(c)["windows"] == ["0.9.1"]


def test_rel3_no_pointer_keeps_the_highest_and_everything_below_it(conn):
    """An older feed with no `current`: the SYS-2 count still sees every build."""
    rf.record_offer_state(conn, [_comp("0.9.61"), _comp("0.9.62"), _comp("0.9.63")],
                          NOW)
    assert sorted(dbmod.get_feed_offered(conn)["windows"]) == [
        "0.9.61", "0.9.62", "0.9.63"]


def _state(records, current=None):
    channel = {"current": current} if current is not None else {}
    return types.SimpleNamespace(feed_cache={"channel": channel,
                                             "valid_records": records,
                                             "checked_at": NOW})


def test_rel3_the_dashboard_offered_is_the_pointer_not_the_highest():
    st = _state([_dash("0.7.57"), _dash("0.7.58")], {"dashboard/linux": "0.7.57"})
    assert rf.offered_dashboard_version(st) == ("0.7.57", True)
    st = _state([_dash("0.7.57"), _dash("0.7.58")])
    assert rf.offered_dashboard_version(st) == ("0.7.58", False)
    assert rf.offered_dashboard_version(types.SimpleNamespace()) == ("", False)


def test_rel3_what_is_running_reports_the_pointed_dashboard(conn, monkeypatch):
    """HEAD's what_is_running took the highest dashboard record, so a staged
    bundle made the HEALTH box say this server was behind the vendor."""
    monkeypatch.setattr(dashboard_update, "image_mode", lambda: True)
    st = _state([_dash("0.7.57"), _dash("99.0.0")], {"dashboard/linux": "0.7.57"})
    out = package_store.what_is_running(conn, None, st)
    assert out["dashboard"]["newest_offered"] == "0.7.57"


def _patch_status(monkeypatch, versions):
    monkeypatch.setattr(dashboard_update, "status", lambda s, a: {
        "image_mode": True, "in_progress": False, "runtime_updates": [],
        "code_updates": [{"version": v, "published_at": "2026-01-01T00:00:00Z"}
                         for v in versions]})
    monkeypatch.setattr(dashboard_update, "read_state", lambda s: {"step": "idle"})


def test_rel4_a_staged_dashboard_bundle_is_not_applied_unattended(
        conn, tmp_path, monkeypatch):
    """logic-release-4: 9.9.9 is on the channel, the pointer still names
    9.9.8 (published without --make-current). HEAD applied code_updates[0],
    9.9.9, restarting every `policy = current` customer onto it."""
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET)
    _patch_status(monkeypatch, ["9.9.9", "9.9.8"])
    st = _state([_dash("9.9.8"), _dash("9.9.9")], {"dashboard/linux": "9.9.8"})
    version, why = rf._dashboard_auto_apply_reason(conn, settings, st, NOW)
    assert version == "9.9.8"
    _patch_status(monkeypatch, ["9.9.9"])       # running 9.9.8 already
    version, why = rf._dashboard_auto_apply_reason(conn, settings, st, NOW)
    assert version == ""
    assert "9.9.9" in why and "not taken automatically" in why
    assert "—" not in why


def test_rel4_no_pointer_keeps_the_highest_first_rule(conn, tmp_path, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET)
    _patch_status(monkeypatch, ["9.9.9", "9.9.8"])
    st = _state([_dash("9.9.8"), _dash("9.9.9")])
    assert rf._dashboard_auto_apply_reason(conn, settings, st, NOW) == ("9.9.9", "")


# --- ui-dash-admin-8 ----------------------------------------------------------

def test_admin8_a_refused_save_keeps_what_the_admin_pasted(tmp_path):
    """ui-dash-admin-8: three fingerprints, one with a typo. HEAD re-rendered
    the panel from the SAVED (empty) values, so all three were lost."""
    good1 = ":".join(["AA"] * 32)
    good2 = ":".join(["BB"] * 32)
    typo = "CC:DD:EE"
    pasted = f"{good1}\n{typo}\n{good2}"
    settings = Settings(db_path=str(tmp_path / "a.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        resp = client.post("/api/v1/setup/android", data={
            "package_name": "com.example.cards",
            "sha256_cert_fingerprints": pasted})
        assert resp.status_code == 200
        assert "not a SHA-256 fingerprint" in resp.text
        for line in (good1, typo, good2):
            assert line in resp.text
        assert 'value="com.example.cards"' in resp.text
        # ...and nothing was saved
        assert client.get("/.well-known/assetlinks.json").json() == []


# ===================================================================== owed round
# Items other groups' builders left for d-ops files (2026-09-25).

import ast as _ast  # noqa: E402
import os as _os  # noqa: E402
import shlex as _shlex  # noqa: E402
import shutil as _shutil  # noqa: E402
import subprocess as _subprocess  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

from ccsync_dashboard.nas import NasError  # noqa: E402
from ccsync_dashboard.nas import synology as _syn  # noqa: E402

_PKG = _Path(__file__).resolve().parents[1] / "src" / "ccsync_dashboard"

K1 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIfirstcomputerkey owen@desktop"
K2 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIsecondcomputerkey owen@laptop"


# --- bug-dash-api-1 (owed from d-api): DSM appends a second computer's key ----

def _git_bash() -> str | None:
    """A POSIX shell that is not WSL's launcher (System32\\bash.exe runs a
    different machine's filesystem). The script under test is what DSM runs."""
    for cand in (r"C:\Program Files\Git\bin\bash.exe", _shutil.which("bash")):
        if cand and _os.path.exists(cand) and "system32" not in cand.lower():
            return cand
    return None


def _real_shell_client(tmp_path, monkeypatch, *, exists=True):
    """A SynologyClient whose SSH half runs the generated script in a real
    shell against a home under tmp_path. chown and getent are stubbed (there
    is no `owen` here); everything else, awk, cat, tail, mv, chmod, stat, is
    the real thing, because the file's contents are the whole point."""
    bash = _git_bash()
    if bash is None:
        pytest.skip("no POSIX shell to run the NAS-side script in")
    homes = tmp_path / "homes"
    (homes / "owen").mkdir(parents=True)
    monkeypatch.setattr(_syn, "HOME_ROOT", homes.as_posix())
    scripts: list[str] = []

    def runner(command, _stdin):
        script = _shlex.split(command)[-1]
        scripts.append(script)
        proc = _subprocess.run(
            [bash, "-c", "chown() { :; }\ngetent() { :; }\n" + script],
            capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout, proc.stderr

    client = _syn.SynologyClient("dsm.example", "ccsync", "pw", False, ssh_runner=runner)
    row = {"username": "owen", "uid": 1030, "groups": ["editors"]} if exists else None
    monkeypatch.setattr(client, "_refuse_non_editor", lambda _u, _a: row)
    keys = homes / "owen" / ".ssh" / "authorized_keys"
    return client, keys, scripts


def test_owed_api1_dsm_adds_a_second_key_and_keeps_the_first(tmp_path, monkeypatch):
    """bug-dash-api-1: approving the laptop's key must leave the desktop's.
    HEAD's SynologyClient has no add_editor_ssh_key, so api.py fell back to
    create_or_update_editor, whose script REPLACES authorized_keys."""
    client, keys, _ = _real_shell_client(tmp_path, monkeypatch)
    keys.parent.mkdir()
    keys.write_bytes((K1 + "\n").encode())
    result = client.add_editor_ssh_key("owen", K2)
    assert keys.read_bytes().decode().splitlines() == [K1, K2]
    assert result["created"] is False and result["username"] == "owen"
    # No tmp file left behind: the write is still tmp + mv.
    assert sorted(p.name for p in keys.parent.iterdir()) == ["authorized_keys"]


def test_owed_api1_a_key_already_there_is_not_written_twice(tmp_path, monkeypatch):
    """Same type and body is the same key, whatever its comment or an options
    prefix on its line."""
    client, keys, _ = _real_shell_client(tmp_path, monkeypatch)
    keys.parent.mkdir()
    body = 'from="10.0.0.0/8" ' + K2.rsplit(" ", 1)[0] + " other-comment\n" + K1 + "\n"
    keys.write_bytes(body.encode())
    client.add_editor_ssh_key("owen", K2)
    assert keys.read_bytes().decode() == body


def test_owed_api1_a_file_without_a_final_newline_is_not_glued(tmp_path, monkeypatch):
    """A hand-edited authorized_keys often has no final newline; appending
    straight after it would fuse the new key into the last line's comment."""
    client, keys, _ = _real_shell_client(tmp_path, monkeypatch)
    keys.parent.mkdir()
    keys.write_bytes(K1.encode())
    client.add_editor_ssh_key("owen", K2)
    assert keys.read_bytes().decode().splitlines() == [K1, K2]


def test_owed_api1_an_account_with_no_key_file_gets_just_the_new_key(tmp_path, monkeypatch):
    client, keys, _ = _real_shell_client(tmp_path, monkeypatch)
    client.add_editor_ssh_key("owen", K2)
    assert keys.read_bytes().decode() == K2 + "\n"


def test_owed_api1_the_append_touches_only_dot_ssh(tmp_path, monkeypatch):
    """Spike 1: chmod/chown of the home or anything under a share deletes the
    Synology ACL. The append script keeps the install script's footprint."""
    client, _keys, scripts = _real_shell_client(tmp_path, monkeypatch)
    client.add_editor_ssh_key("owen", K2)
    script = scripts[0]
    for line in script.splitlines():
        if line.strip().startswith(("chmod", "chown")):
            assert '"$home/.ssh"' in line or '"$keys"' in line, line
    assert "mv -f" in script and ".authorized_keys.ccsync" in script


def test_owed_api1_a_key_that_could_not_be_written_raises(monkeypatch):
    """The approve route keeps the queued offer only when the backend raises.
    create_or_update_editor turns an SSH failure into a warning (the account
    exists, so the create half succeeded); the add call has no other half, so
    a warning would have dropped the offer with no key on the NAS."""
    client = _syn.SynologyClient("dsm.example", "ccsync", "pw", False,
                                 ssh_runner=lambda _c, _s: (3, "MISSING_HOME\n", ""))
    monkeypatch.setattr(client, "_refuse_non_editor",
                        lambda _u, _a: {"username": "owen", "uid": 1030})
    with pytest.raises(NasError, match="User Home service is off"):
        client.add_editor_ssh_key("owen", K2)

    def down(_c, _s):
        raise NasError("SSH to dsm.example:22 failed: simulated outage")
    client.ssh_runner = down
    with pytest.raises(NasError, match="simulated outage"):
        client.add_editor_ssh_key("owen", K2)


def test_owed_api1_a_multi_line_key_is_refused_before_any_ssh(monkeypatch):
    ran: list = []
    client = _syn.SynologyClient("dsm.example", "ccsync", "pw", False,
                                 ssh_runner=lambda c, s: ran.append(c) or (0, "", ""))
    monkeypatch.setattr(client, "_refuse_non_editor",
                        lambda _u, _a: {"username": "owen", "uid": 1030})
    with pytest.raises(NasError):
        client.add_editor_ssh_key("owen", K2 + "\n" + K1)
    with pytest.raises(NasError):
        client.add_editor_ssh_key("owen", "ssh-ed25519")
    assert ran == []


def test_owed_api1_no_account_yet_goes_down_the_create_path(monkeypatch):
    """An account that does not exist has no other key to keep; create it."""
    client = _syn.SynologyClient("dsm.example", "ccsync", "pw", False,
                                 ssh_runner=lambda _c, _s: (0, "", ""))
    monkeypatch.setattr(client, "_refuse_non_editor", lambda _u, _a: None)
    calls: list = []
    monkeypatch.setattr(client, "create_or_update_editor",
                        lambda u, k, n=None: calls.append((u, k, n)) or {"created": True})
    assert client.add_editor_ssh_key("owen", K2) == {"created": True}
    assert calls == [("owen", K2, None)]


# --- bug-dash-cards-jobs-4 (owed from d-cards): ytdl takes login_gate's verdict first

def _run_gate(scope):
    seen: dict = {}

    async def spy(s, receive, send):
        seen["headers"] = dict(s["headers"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_m):
        return None

    gate = ytdl.YtdlGate(spy, SECRET, None)
    asyncio.run(gate(scope, receive, send))
    return seen["headers"]


def test_owed_cards_jobs_4_the_resolved_identity_wins_over_the_cookie():
    """The same rule broll/music's gates follow: login_gate's answer in the
    request state wins. Before, with no dashboard app in the scope, the gate
    read the cookie and stamped its owner (alice) though login_gate had
    resolved bob."""
    cookie = auth.make_session_cookie(SECRET, "alice").encode()
    headers = _run_gate({
        "type": "http", "method": "GET", "path": "/ytdl/api/me", "root_path": "/ytdl",
        "state": {"ccsync_session": ("bob", "sid", True)},
        "headers": [(b"cookie", b"ccsync_session=" + cookie)]})
    assert headers.get(b"x-ccsync-user") == b"bob"


def test_owed_cards_jobs_4_a_not_live_verdict_mints_no_header_without_the_app():
    """A revoked session (login_gate's (None, None, False)) must not be
    resurrected from the cookie's signature, app or no app."""
    cookie = auth.make_session_cookie(SECRET, "revoked-rita").encode()
    headers = _run_gate({
        "type": "http", "method": "GET", "path": "/ytdl/api/me", "root_path": "/ytdl",
        "state": {"ccsync_session": (None, None, False)},
        "headers": [(b"cookie", b"ccsync_session=" + cookie)]})
    assert b"x-ccsync-user" not in headers


def test_owed_cards_jobs_4_no_verdict_still_reads_the_cookie():
    cookie = auth.make_session_cookie(SECRET, "carol").encode()
    headers = _run_gate({
        "type": "http", "method": "GET", "path": "/ytdl/api/me", "root_path": "/ytdl",
        "headers": [(b"cookie", b"ccsync_session=" + cookie)]})
    assert headers.get(b"x-ccsync-user") == b"carol"


# --- logic-admin-6 (owed from d-ui): the unsigned refusal on a feed site ------

def _unsigned_refusal(tmp_path, conn, **kw):
    from test_packages import insert_unsigned_package
    settings = Settings(db_path=str(tmp_path / "rel.db"), session_secret=SECRET,
                        packages_dir=str(tmp_path / "pkgs"), **kw)
    insert_unsigned_package(conn, settings, "windows", "9.9.9")
    return package_store.make_current_refusal(conn, settings, kind="companion",
                                              platform="windows", version="9.9.9")


def test_owed_admin6_a_feed_site_is_sent_to_the_vendor_list(tmp_path, conn):
    """HEAD told every site to "Republish it through tools\\ship.cmd", the
    vendor's own pathway A; a customer on the feed has no such script."""
    status, detail = _unsigned_refusal(
        tmp_path, conn, release_feed_url="https://feed.example/channel.json")
    assert status == 409
    assert "AVAILABLE FROM THE VENDOR" in detail
    assert "ship.cmd" not in detail
    assert "type the version number (9.9.9)" in detail


def test_owed_admin6_a_site_with_no_feed_keeps_ship_cmd(tmp_path, conn):
    status, detail = _unsigned_refusal(tmp_path, conn)
    assert status == 409
    assert "tools\\ship.cmd" in detail and "AVAILABLE FROM THE VENDOR" not in detail


# --- ui-copy-6 (owed from d-ui): no " -- " in d-ops copy ------------------------

def _typewriter_dashes(path):
    """d-ui's scan (test_bug_hunt_2026_09_24_w2_d-ui.py), plus one exclusion:
    dashboard_update's _STAGE_VERIFY_SOURCE is a Python script the new tree
    runs, not text anyone reads."""
    tree = _ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                             _ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, _ast.Expr) and isinstance(first.value, _ast.Constant)
                    and isinstance(first.value.value, str)):
                skip.add(id(first.value))
        if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                and node.func.attr in ("debug", "info", "warning", "error",
                                       "exception", "critical")):
            skip.update(id(n) for n in _ast.walk(node))
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)
                and node.targets[0].id == "_STAGE_VERIFY_SOURCE"):
            skip.update(id(n) for n in _ast.walk(node))
    return [(n.lineno, n.value) for n in _ast.walk(tree)
            if isinstance(n, _ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip and " -- " in n.value]


@pytest.mark.parametrize("rel", [
    "dashboard_update.py", "release_feed.py", "ai_providers.py",
    "nas/synology.py", "nas/truenas.py", "nas/factory.py",
    "package_store.py", "runtime_id.py",
])
def test_owed_copy6_d_ops_copy_has_no_typewriter_em_dash(rel):
    """HEAD: 56 user-reachable " -- " literals across these eight files (HTTP
    details, refusal messages the admin pages show, NAS warnings)."""
    hits = _typewriter_dashes(_PKG / rel)
    assert not hits, hits


# --- owed round 2 (2026-09-25) ----------------------------------------------
# The crash-file counter: a later crash of a burst must never be the one the
# prune takes first, and a slot freed by the prune must not go to the newest.

def _burst(settings, n, when="2026-09-25T10:00:00+00:00"):
    out = []
    for i in range(n):
        out.append(crash_report.write_report(
            {"when": when, "thread": "ThreadPoolExecutor-0_0",
             "exception": {"message": f"crash {i}"}}, settings))
    return out


def _messages(directory):
    import json as _json
    return sorted(_json.loads(p.read_text(encoding="utf-8"))["exception"]["message"]
                  for p in directory.glob("*.json"))


def test_owed2_the_prune_keeps_the_LATEST_crashes_of_a_burst(tmp_path, monkeypatch):
    monkeypatch.delenv("DASH_CRASH_DIR", raising=False)
    monkeypatch.setattr(crash_report, "MAX_CRASH_FILES", 2)
    settings = _S(tmp_path / "dashboard.db")
    _burst(settings, 3)
    assert _messages(tmp_path / "crashes") == ["crash 1", "crash 2"]


def test_owed2_a_slot_the_prune_freed_does_not_go_to_the_newest(tmp_path, monkeypatch):
    monkeypatch.delenv("DASH_CRASH_DIR", raising=False)
    monkeypatch.setattr(crash_report, "MAX_CRASH_FILES", 2)
    settings = _S(tmp_path / "dashboard.db")
    _burst(settings, 4)
    assert _messages(tmp_path / "crashes") == ["crash 2", "crash 3"]


def test_owed2_ten_and_more_in_one_second_stay_in_order(tmp_path, monkeypatch):
    monkeypatch.delenv("DASH_CRASH_DIR", raising=False)
    monkeypatch.setattr(crash_report, "MAX_CRASH_FILES", 5)
    settings = _S(tmp_path / "dashboard.db")
    _burst(settings, 12)
    assert set(_messages(tmp_path / "crashes")) == {f"crash {i}" for i in range(7, 12)}


def test_owed2_a_thread_named_like_a_counter_is_not_one(tmp_path):
    older = tmp_path / "20260925T100000+0000-Thread.json"
    worker = tmp_path / "20260925T100000+0000-Thread-1.json"
    assert crash_report._age_key(worker)[0].endswith("Thread-1")
    assert crash_report._age_key(older) < crash_report._age_key(worker)


def test_owed2_the_help_doc_names_the_companions_real_diagnostics_route():
    from pathlib import Path as _P
    from ccsync_dashboard import health
    doc = (_P(__file__).resolve().parents[2] / "docs" / "HOW_IT_WORKS.md").read_text(
        encoding="utf-8")
    assert "Settings > Help > Copy diagnostics" not in doc
    assert doc.count(health.COMPANION_DIAGNOSTICS_PATH) >= 2
