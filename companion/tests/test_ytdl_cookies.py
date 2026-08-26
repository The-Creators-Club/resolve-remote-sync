"""ytdl_cookies: where the local downloader's signed-in cookies live, the
shape validator, and the install-from-a-picked-file path the tray uses.

No browser, no network, no real YouTube session -- a cookies.txt is just text,
and every case here is built from a few tab-separated lines.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ccsync_companion import ytdl_cookies as yc


# ---------------------------------------------------------------------------
# fixtures: cookie files as text
# ---------------------------------------------------------------------------


def _line(domain, name, value="x", expiry="1900000000"):
    return f"{domain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}"


def _signed_in(names=("SID", "SAPISID", "HSID", "LOGIN_INFO")) -> str:
    header = "# Netscape HTTP Cookie File\n"
    return header + "\n".join(_line(".youtube.com", n) for n in names) + "\n"


def _logged_out() -> str:
    # The __Secure-3P* / visitor set a signed-OUT export carries -- exactly
    # what the NAS's half-broken file had (2026-08-16), which does NOT auth.
    header = "# Netscape HTTP Cookie File\n"
    names = ("__Secure-3PSID", "VISITOR_INFO1_LIVE", "PREF", "YSC")
    return header + "\n".join(_line(".youtube.com", n) for n in names) + "\n"


# ---------------------------------------------------------------------------
# validate: SHAPE, not liveness
# ---------------------------------------------------------------------------


def test_a_signed_in_youtube_export_validates():
    ok, msg = yc.validate(_signed_in())
    assert ok is True and "login cookies" in msg


def test_a_logged_out_export_is_rejected_with_a_reason():
    ok, msg = yc.validate(_logged_out())
    assert ok is False and "signed-in" in msg


def test_the_nas_partial_session_shape_is_rejected():
    """The concrete file that started this: __Secure-3P* only, no SID."""
    ok, _ = yc.validate("# Netscape HTTP Cookie File\n"
                        + _line(".youtube.com", "__Secure-3PSID") + "\n"
                        + _line(".youtube.com", "__Secure-3PAPISID") + "\n")
    assert ok is False


def test_one_session_cookie_is_not_enough():
    ok, _ = yc.validate("# Netscape HTTP Cookie File\n" + _line(".youtube.com", "SID") + "\n")
    assert ok is False, "a lone SID is more likely a fragment than a session"


def test_non_youtube_session_cookies_do_not_count():
    """SID on .google.com is a Google session, not a youtube one; the
    downloader wants youtube.com cookies."""
    ok, _ = yc.validate("# Netscape HTTP Cookie File\n"
                        + _line(".google.com", "SID") + "\n"
                        + _line(".google.com", "SAPISID") + "\n")
    assert ok is False


def test_a_non_netscape_file_is_rejected():
    ok, msg = yc.validate("SID=abc; SAPISID=def; this is a header string")
    assert ok is False and "Netscape" in msg


@pytest.mark.parametrize("junk", ["", None, "   ", "not a cookie file at all"])
def test_garbage_is_rejected_not_crashed(junk):
    ok, _ = yc.validate(junk)
    assert ok is False


# ---------------------------------------------------------------------------
# resolve: config key beats default path beats nothing
# ---------------------------------------------------------------------------


def test_resolve_prefers_the_config_key(tmp_path, monkeypatch):
    monkeypatch.setattr(yc, "default_cookies_path", lambda: tmp_path / "default.txt")
    (tmp_path / "default.txt").write_text(_signed_in())
    explicit = tmp_path / "mine.txt"
    explicit.write_text(_signed_in())

    assert yc.resolve({"ytdl_cookies_file": str(explicit)}) == str(explicit)


def test_resolve_falls_back_to_the_default_path(tmp_path, monkeypatch):
    default = tmp_path / "youtube-cookies.txt"
    default.write_text(_signed_in())
    monkeypatch.setattr(yc, "default_cookies_path", lambda: default)

    assert yc.resolve({}) == str(default)
    assert yc.resolve({"ytdl_cookies_file": ""}) == str(default)


def test_resolve_is_none_when_nothing_is_there(tmp_path, monkeypatch):
    monkeypatch.setattr(yc, "default_cookies_path", lambda: tmp_path / "nope.txt")
    assert yc.resolve({}) is None


def test_a_configured_but_missing_path_is_none_not_the_default(tmp_path, monkeypatch):
    """A configured-but-absent path resolves to None (yt-dlp aborts on a
    missing --cookies file), and does NOT silently fall through to the default
    -- the editor asked for a specific file."""
    default = tmp_path / "youtube-cookies.txt"
    default.write_text(_signed_in())
    monkeypatch.setattr(yc, "default_cookies_path", lambda: default)

    assert yc.resolve({"ytdl_cookies_file": str(tmp_path / "gone.txt")}) is None


# ---------------------------------------------------------------------------
# install: validate, then copy 0600 to the default path
# ---------------------------------------------------------------------------


def test_install_copies_a_valid_file_to_the_default_path(tmp_path):
    src = tmp_path / "export.txt"
    src.write_text(_signed_in())
    dest = tmp_path / ".ccsync" / "youtube-cookies.txt"

    ok, msg = yc.install(str(src), dest=dest)

    assert ok is True and "saved" in msg
    assert dest.read_text() == _signed_in()
    assert not dest.with_suffix(dest.suffix + ".new").exists()
    if sys.platform != "win32":
        assert (os.stat(dest).st_mode & 0o777) == 0o600


def test_install_hardens_the_temp_file_before_the_rename(tmp_path, monkeypatch):
    """os.chmod(0o600) is a NO-OP on Windows, where most of this fleet's
    editors are, so the one file here that is a logged-in Google account sat
    at whatever the download dir's inherited ACL was (2026-08-17,
    COMMERCIAL_READINESS.md item 5). secretfile.harden is the cross-platform
    answer, and it must land on the TEMP file -- after the replace the secret
    has already existed under wider permissions.
    """
    from ccsync_companion import secretfile

    src = tmp_path / "export.txt"
    src.write_text(_signed_in())
    dest = tmp_path / ".ccsync" / "youtube-cookies.txt"
    hardened: list = []
    monkeypatch.setattr(secretfile, "harden",
                        lambda path: hardened.append((Path(path), Path(path).exists())) or True)

    assert yc.install(str(src), dest=dest)[0] is True
    assert hardened == [(dest.with_suffix(dest.suffix + ".new"), True)]


def test_install_refuses_a_logged_out_export_and_writes_nothing(tmp_path):
    src = tmp_path / "export.txt"
    src.write_text(_logged_out())
    dest = tmp_path / "youtube-cookies.txt"

    ok, msg = yc.install(str(src), dest=dest)

    assert ok is False and "signed-in" in msg
    assert not dest.exists()


def test_install_of_a_missing_file_is_a_clean_error(tmp_path):
    ok, msg = yc.install(str(tmp_path / "nope.txt"), dest=tmp_path / "out.txt")
    assert ok is False and "read" in msg


def test_install_overwrites_a_previous_session(tmp_path):
    dest = tmp_path / "youtube-cookies.txt"
    dest.write_text(_signed_in(names=("SID", "SAPISID")))
    newer = tmp_path / "new.txt"
    newer.write_text(_signed_in(names=("SID", "SAPISID", "HSID", "SSID", "LOGIN_INFO")))

    ok, _ = yc.install(str(newer), dest=dest)

    assert ok is True
    assert dest.read_text() == newer.read_text()


# ---------------------------------------------------------------------------
# the flagged session (CR-80, 2026-08-26, plan WP4)
# ---------------------------------------------------------------------------


def test_a_flagged_session_is_a_stale_signature():
    """The one-line change the plan says should go in regardless of the rest.

    Until 2026-08-26 the classifier did not carry this phrase, so a signed-in
    session YouTube had FLAGGED never got marked stale: the executor failed N
    clips with one opaque string and the tray went on saying the sign-in was
    fine. It is not an expiry and not a rotation -- the cookies still
    authenticate -- which is why nothing else in this module would ever have
    caught it.
    """
    flagged = "ERROR: [youtube] aaaaaaaaaaa: The page needs to be reloaded."
    assert yc.classify_failure(flagged, cookies_used=True) == \
        yc.ACCOUNT_FLAG_SIGNATURE
    assert yc.ACCOUNT_FLAG_SIGNATURE in yc.STALE_SIGNATURES
    # Unchanged semantics: without cookies this says nothing about the
    # editor's sign-in, because the session was never sent.
    assert yc.classify_failure(flagged, cookies_used=False) is None


def test_the_recorded_reason_is_written_for_the_editor():
    """The reason is read by a person (tray._youtube_warning_line). "yt-dlp:
    the page needs to be reloaded" is the string that cost CR-80 a day, and it
    would have sent an editor to re-export the same flagged session. It says
    what is happening and that downloads carry on without it, and it keeps the
    signature inside so the tray can still tell the two cases apart."""
    reason = yc.stale_reason(yc.ACCOUNT_FLAG_SIGNATURE)
    assert "refusing your signed-in session" in reason
    assert "continuing without it" in reason
    assert yc.ACCOUNT_FLAG_SIGNATURE in reason.lower()
    assert " -- " not in reason and "—" not in reason
    # Every other signature keeps the shape it had.
    assert yc.stale_reason("cookies are no longer valid") == \
        "yt-dlp: cookies are no longer valid"
