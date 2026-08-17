"""ytdl_browser_login: the one-click YouTube sign-in (2026-08-17).

No browser, no network: the flow is driven through its seams (launcher,
session_factory, wait_devtools, sleep/clock), the WebSocket framing is
checked against RFC 6455's own vectors, and the cookies text is fed back
through ytdl_cookies.validate so the two halves cannot drift.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ccsync_companion import ytdl_browser_login as bl
from ccsync_companion import ytdl_cookies


@pytest.fixture(autouse=True)
def _site_enabled(monkeypatch):
    monkeypatch.setattr(ytdl_cookies, "enabled", lambda: True)


# ------------------------------------------------------------ discovery
def test_find_browser_prefers_the_env_override_when_it_is_a_file():
    b = bl.find_browser(environ={bl.BROWSER_ENV: "/opt/odd/chrome"}, is_file=lambda p: p == "/opt/odd/chrome",
                        which=lambda n: None)
    assert b is not None and b.path == "/opt/odd/chrome"


def test_find_browser_walks_the_platform_candidates_in_order():
    cands = bl._candidates()
    first_name, first_paths = cands[0]
    target = next(p for p in first_paths if p)
    b = bl.find_browser(environ={}, is_file=lambda p: p == target, which=lambda n: None)
    assert b is not None and b.name == first_name and b.path == target


def test_find_browser_none_when_nothing_is_installed():
    assert bl.find_browser(environ={}, is_file=lambda p: False, which=lambda n: None) is None


def test_launch_args_use_a_private_profile_and_loopback_devtools(tmp_path):
    argv = bl.launch_args(bl.Browser("Edge", "C:/x/msedge.exe"), tmp_path / "prof", 43111)
    assert argv[0] == "C:/x/msedge.exe"
    assert f"--user-data-dir={tmp_path / 'prof'}" in argv
    assert "--remote-debugging-port=43111" in argv
    assert "--no-first-run" in argv and "--disable-sync" in argv
    assert argv[-1] == bl.LOGIN_URL and "youtube.com" in bl.LOGIN_URL


# ------------------------------------------------------------ websocket framing (RFC 6455 §5.7)
def test_encode_frame_matches_the_rfc_masked_hello_example():
    frame = bl.encode_frame(b"Hello", 0x1, mask_key=bytes([0x37, 0xFA, 0x21, 0x3D]))
    assert frame == bytes([0x81, 0x85, 0x37, 0xFA, 0x21, 0x3D, 0x7F, 0x9F, 0x4D, 0x51, 0x58])


def _reader(data: bytes):
    buf = bytearray(data)

    def read(n):
        if len(buf) < n:
            raise ConnectionError("short")
        out = bytes(buf[:n])
        del buf[:n]
        return out
    return read


def test_decode_frame_reads_unmasked_and_masked_hello():
    fin, op, payload = bl.decode_frame(_reader(bytes([0x81, 0x05]) + b"Hello"))
    assert (fin, op, payload) == (True, 0x1, b"Hello")
    masked = bytes([0x81, 0x85, 0x37, 0xFA, 0x21, 0x3D, 0x7F, 0x9F, 0x4D, 0x51, 0x58])
    assert bl.decode_frame(_reader(masked)) == (True, 0x1, b"Hello")


def test_frames_round_trip_at_the_126_and_127_length_boundaries():
    for n in (125, 126, 65535, 65536, 70000):
        payload = bytes((i * 7) & 0xFF for i in range(n))
        frame = bl.encode_frame(payload, 0x1)
        # Length encoding is what changes at the boundaries.
        if n < 126:
            assert frame[1] & 0x7F == n
        elif n < 65536:
            assert frame[1] & 0x7F == 126 and struct.unpack("!H", frame[2:4])[0] == n
        else:
            assert frame[1] & 0x7F == 127 and struct.unpack("!Q", frame[2:10])[0] == n
        assert bl.decode_frame(_reader(frame)) == (True, 0x1, payload)


# ------------------------------------------------------------ cookies
def _cookie(name, value="v", domain=".youtube.com", **kw):
    c = {"name": name, "value": value, "domain": domain, "path": "/", "secure": True,
         "httpOnly": False, "expires": 1900000000, "session": False}
    c.update(kw)
    return c


def test_relevant_keeps_youtube_and_google_and_drops_the_rest():
    cookies = [_cookie("SID"), _cookie("NID", domain=".google.com"), _cookie("x", domain=".doubleclick.net"),
               _cookie("y", domain="notyoutube.com")]
    assert [c["name"] for c in bl.relevant(cookies)] == ["SID", "NID"]


def test_signed_in_needs_two_real_login_cookies_on_youtube():
    assert not bl.signed_in([_cookie("PREF"), _cookie("VISITOR_INFO1_LIVE")])
    assert not bl.signed_in([_cookie("SID"), _cookie("SAPISID", domain=".google.com")])
    assert bl.signed_in([_cookie("SID"), _cookie("SAPISID")])


def test_netscape_text_is_accepted_by_ytdl_cookies_validate_and_marks_httponly_and_session():
    cookies = [_cookie("SID"), _cookie("SAPISID"),
               _cookie("LOGIN_INFO", httpOnly=True),
               _cookie("YSC", expires=-1, session=True),
               _cookie("host", domain="www.youtube.com", hostOnly=True)]
    text = bl.netscape_text(cookies)
    ok, msg = ytdl_cookies.validate(text)
    assert ok, msg
    lines = [l for l in text.splitlines() if l and not l.startswith("# ")]
    assert lines[0].split("\t") == [".youtube.com", "TRUE", "/", "TRUE", "1900000000", "SID", "v"]
    assert any(l.startswith("#HttpOnly_.youtube.com\t") and "\tLOGIN_INFO\t" in l for l in lines)
    assert any("\t0\tYSC\t" in l for l in lines)                       # session cookie -> expiry 0
    assert any(l.startswith("www.youtube.com\tFALSE\t") for l in lines)  # host-only -> no subdomains


def test_netscape_text_skips_a_cookie_that_would_break_the_line_format():
    text = bl.netscape_text([_cookie("SID"), _cookie("bad\tname"), _cookie("SAPISID", value="a\nb")])
    assert "bad" not in text and "a\nb" not in text and "\tSID\t" in text


# ------------------------------------------------------------ the flow
class _Proc:
    def __init__(self):
        self.rc = None
        self.terminated = False

    def poll(self):
        return self.rc

    def terminate(self):
        self.terminated = True
        self.rc = 0

    def kill(self):
        self.rc = -9


class _Session:
    """Scripted Network.getAllCookies answers; records every call."""

    def __init__(self, cookie_states):
        self.states = list(cookie_states)
        self.calls = []
        self.closed = False

    def call(self, method, params=None, timeout=30.0):
        self.calls.append((method, params or {}))
        if method == "Network.getAllCookies":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return {"cookies": state}
        return {}

    def close(self):
        self.closed = True


def _flow(monkeypatch, tmp_path, session, proc=None, **kw):
    proc = proc or _Proc()
    launched = []
    sleeps = []
    t = [0.0]

    def sleep(s):
        sleeps.append(s)
        t[0] += s

    def clock():
        return t[0]

    installed = []

    def install_text(text):
        installed.append(text)
        return True, "YouTube sign-in saved"

    out = bl.run(
        browser=bl.Browser("FakeEdge", "/fake/edge"),
        profile=tmp_path / "prof",
        launcher=lambda argv: (launched.append(argv), proc)[1],
        session_factory=lambda port: session,
        wait_devtools=lambda port, alive, sleep, clock: True,
        port_picker=lambda: 40123,
        install_text=install_text,
        sleep=sleep, clock=clock, **kw,
    )
    return out, dict(launched=launched, sleeps=sleeps, installed=installed, proc=proc)


def test_happy_path_waits_for_login_writes_cookies_shows_done_page_and_closes(tmp_path, monkeypatch):
    session = _Session([[_cookie("PREF")], [_cookie("PREF")], [_cookie("SID"), _cookie("SAPISID"),
                                                                 _cookie("x", domain=".doubleclick.net")]])
    out, st = _flow(monkeypatch, tmp_path, session)
    assert out.ok, out.message
    assert out.cookies_written == 2                       # doubleclick dropped
    assert st["launched"] and "--remote-debugging-port=40123" in st["launched"][0]
    assert (tmp_path / "prof").is_dir()
    assert "\tSID\t" in st["installed"][0] and "doubleclick" not in st["installed"][0]
    methods = [m for m, _ in session.calls]
    assert methods.count("Network.getAllCookies") == 3
    nav = next(p for m, p in session.calls if m == "Page.navigate")
    assert nav["url"].startswith("data:text/html") and "Signed%20in" in nav["url"]
    assert bl.DONE_PAGE_SECONDS in st["sleeps"]           # the two-second page
    assert methods[-1] == "Browser.close" and session.closed
    # order: navigate happens AFTER the file is written, so a crash mid-way never shows a false tick
    assert methods.index("Page.navigate") > methods.index("Network.getAllCookies")


def test_browser_closed_by_the_person_before_login_is_a_clean_failure(tmp_path, monkeypatch):
    proc = _Proc()
    session = _Session([[_cookie("PREF")]])
    # the process dies after the first poll
    polls = [None, 0, 0, 0]
    proc.poll = lambda: polls.pop(0) if polls else 0
    out, st = _flow(monkeypatch, tmp_path, session, proc=proc)
    assert not out.ok and "closed" in out.message
    assert st["installed"] == []


def test_login_timeout_saves_nothing_and_still_shuts_the_browser(tmp_path, monkeypatch):
    session = _Session([[_cookie("PREF")]])
    out, st = _flow(monkeypatch, tmp_path, session, login_timeout=3.0)
    assert not out.ok and "did not finish" in out.message
    assert st["installed"] == []
    assert ("Browser.close", {}) in session.calls


def test_disabled_site_refuses_before_touching_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdl_cookies, "enabled", lambda: False)
    launched = []
    out = bl.run(browser=bl.Browser("E", "/e"), profile=tmp_path / "p",
                 launcher=lambda argv: launched.append(argv))
    assert not out.ok and out.message == ytdl_cookies.OFF_MESSAGE
    assert launched == [] and not (tmp_path / "p").exists()


def test_no_browser_is_a_message_pointing_at_the_file_path(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "find_browser", lambda: None)
    out = bl.run(profile=tmp_path / "p")
    assert not out.ok and "cookies.txt" in out.message


def test_a_session_that_drops_is_reattached_not_fatal(tmp_path, monkeypatch):
    class Flaky(_Session):
        def __init__(self):
            super().__init__([[_cookie("SID"), _cookie("SAPISID")]])
            self.first = True

        def call(self, method, params=None, timeout=30.0):
            if method == "Network.getAllCookies" and self.first:
                self.first = False
                raise ConnectionError("target went away")
            return super().call(method, params, timeout)

    session = Flaky()
    out, st = _flow(monkeypatch, tmp_path, session)
    assert out.ok, out.message
    assert st["installed"]


# ------------------------------------------------------------ ytdl_cookies.install_text
def test_install_text_writes_hardened_default_path(tmp_path, monkeypatch):
    dest = tmp_path / "youtube-cookies.txt"
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: dest)
    text = bl.netscape_text([_cookie("SID"), _cookie("SAPISID")])
    ok, msg = ytdl_cookies.install_text(text)
    assert ok, msg
    assert dest.read_text(encoding="utf-8") == text
    assert not dest.with_suffix(".txt.new").exists()


def test_install_text_refuses_a_logged_out_export(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: tmp_path / "c.txt")
    ok, msg = ytdl_cookies.install_text(bl.netscape_text([_cookie("PREF")]))
    assert not ok and "signed-in" in msg and not (tmp_path / "c.txt").exists()


# ------------------------------------------------------------ the tray handler
class _App:
    def __init__(self):
        self.notices = []
        self.config = {}

    def _notify_tray(self, msg, title="ccsync-companion"):
        self.notices.append(msg)


def test_tray_sign_in_runs_the_browser_flow_and_reports_its_message(monkeypatch):
    from ccsync_companion import tray
    app = _App()
    seen = {}

    def runner(browser=None):
        seen["browser"] = browser
        return bl.Outcome(True, "YouTube sign-in saved", cookies_written=7)

    tray._youtube_sign_in(app, runner=runner, finder=lambda: bl.Browser("Edge", "/e"))
    assert seen["browser"].name == "Edge"
    assert app.notices[0].startswith("Edge is opening")
    assert app.notices[-1] == "YouTube sign-in saved"


def test_tray_sign_in_falls_back_to_the_file_picker_when_no_browser(monkeypatch):
    from ccsync_companion import tray
    app = _App()
    picked = []
    # Never let the real Tk picker open in a test.
    monkeypatch.setattr(tray, "_install_youtube_cookies", lambda a, picker=None: picked.append(a))
    tray._youtube_sign_in(app, runner=lambda browser=None: pytest.fail("must not run"), finder=lambda: None)
    assert picked == [app]
    assert app.notices and "cookies.txt" in app.notices[0]


def test_tray_sign_in_survives_a_crashing_flow(monkeypatch):
    from ccsync_companion import tray
    app = _App()

    def boom(browser=None):
        raise RuntimeError("cdp exploded")

    tray._youtube_sign_in(app, runner=boom, finder=lambda: bl.Browser("Chrome", "/c"))
    assert "failed unexpectedly" in app.notices[-1]


# ------------------------------------------------------------ session health (rotated / expired)
def _netscape(*names, expiry=1900000000):
    return bl.netscape_text([_cookie(n, expires=expiry) for n in names])


def test_health_none_without_a_cookies_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: tmp_path / "absent.txt")
    assert ytdl_cookies.health({}, path=tmp_path / "status.json")["status"] == ytdl_cookies.STATUS_NONE


def test_health_ok_then_stale_after_a_refused_download_then_ok_after_resignin(tmp_path, monkeypatch):
    dest = tmp_path / "youtube-cookies.txt"
    status = tmp_path / "status.json"
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: dest)
    monkeypatch.setattr(ytdl_cookies, "status_path", lambda: status)
    ok, _ = ytdl_cookies.install_text(_netscape("SID", "SAPISID"))
    assert ok
    assert ytdl_cookies.health({}, path=status)["status"] == ytdl_cookies.STATUS_OK

    ytdl_cookies.mark_stale("yt-dlp: cookies are no longer valid", path=status)
    h = ytdl_cookies.health({}, path=status)
    assert h["status"] == ytdl_cookies.STATUS_STALE and "no longer valid" in h["reason"]

    # a fresh sign-in clears it
    ok, _ = ytdl_cookies.install_text(_netscape("SID", "SAPISID"))
    assert ok and ytdl_cookies.health({}, path=status)["status"] == ytdl_cookies.STATUS_OK


def test_health_expired_when_the_login_cookies_are_past_their_expiry(tmp_path, monkeypatch):
    dest = tmp_path / "youtube-cookies.txt"
    monkeypatch.setattr(ytdl_cookies, "default_cookies_path", lambda: dest)
    ok, _ = ytdl_cookies.install_text(_netscape("SID", "SAPISID", expiry=1700000000))
    assert ok
    assert ytdl_cookies.health({}, path=tmp_path / "s.json", now=1800000000)["status"] == ytdl_cookies.STATUS_EXPIRED
    assert ytdl_cookies.health({}, path=tmp_path / "s.json", now=1600000000)["status"] == ytdl_cookies.STATUS_OK


def test_classify_failure_only_counts_when_cookies_were_sent():
    rotated = ("WARNING: [youtube] The provided YouTube account cookies are no longer valid. "
               "They have likely been rotated in the browser as a security measure.")
    assert ytdl_cookies.classify_failure(rotated, cookies_used=True)
    assert ytdl_cookies.classify_failure("ERROR: Sign in to confirm you're not a bot", cookies_used=True)
    assert ytdl_cookies.classify_failure(rotated, cookies_used=False) is None
    assert ytdl_cookies.classify_failure("ERROR: Private video", cookies_used=True) is None


def test_executor_marks_stale_once_per_batch_and_ok_again_on_success(tmp_path, monkeypatch):
    from ccsync_companion import ytdl_executor as ex
    calls = []
    monkeypatch.setattr(ytdl_cookies, "mark_stale", lambda reason, path=None: calls.append(("stale", reason)))
    monkeypatch.setattr(ytdl_cookies, "mark_ok", lambda reason="", path=None: calls.append(("ok", reason)))
    monkeypatch.setattr(ex, "_cookies_file", lambda cfg: str(tmp_path / "c.txt"))

    class Proc:
        def __init__(self, rc, err=""):
            self.returncode, self.stderr = rc, err

    outcomes = [Proc(1, "ERROR: [youtube] abc: Sign in to confirm you're not a bot"),
                Proc(1, "ERROR: [youtube] def: Sign in to confirm you're not a bot"),
                Proc(0)]
    job = ex.DownloadJob.__new__(ex.DownloadJob)
    job.deps = type("D", (), {"cfg": {}, "run": lambda self, argv, t, on_spawn: outcomes.pop(0)})()
    job._lock = __import__("threading").Lock()
    job._proc = None
    job.job_id = "j1"
    job._register_proc = lambda p: None
    monkeypatch.setattr(job, "build_argv", lambda url, outdir, q: ["yt-dlp"], raising=False)

    assert job._run_ytdlp("u", str(tmp_path), "1080p")[0] is False
    assert job._run_ytdlp("u", str(tmp_path), "1080p")[0] is False
    assert job._run_ytdlp("u", str(tmp_path), "1080p")[0] is True
    assert [c[0] for c in calls] == ["stale", "ok"]          # once, then cleared


def test_tray_warns_once_when_the_session_goes_stale_and_relabels_the_item(monkeypatch):
    from ccsync_companion import tray
    app = _App()
    snap = {"ytdl_youtube_signin": True,
            "ytdl_cookies_health": {"status": ytdl_cookies.STATUS_STALE, "reason": "yt-dlp: rotated"}}
    tray._maybe_warn_youtube_session(app, snap)
    tray._maybe_warn_youtube_session(app, snap)          # same state: no second balloon
    assert len(app.notices) == 1 and "no longer works" in app.notices[0]
    snap["ytdl_cookies_health"] = {"status": ytdl_cookies.STATUS_OK}
    tray._maybe_warn_youtube_session(app, snap)          # recovered: silent, and re-armed
    snap["ytdl_cookies_health"] = {"status": ytdl_cookies.STATUS_EXPIRED}
    tray._maybe_warn_youtube_session(app, snap)
    assert len(app.notices) == 2 and "expired" in app.notices[1]
    assert "expired" in tray._youtube_warning_line(snap)
