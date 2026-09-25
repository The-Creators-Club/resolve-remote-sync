"""Account page 2026-09-25, group B: the session helpers the account page's
"signed-in browsers" panel stands on (docs/ACCOUNT_PAGE_FEATURES.md 3.4) and
auth.admin_source (3.1).

- sessions.describe_client turns a stored "<ip> <UA>" into words we chose;
- SessionStore.revoke_by_handle revokes ONE of a person's own sessions by its
  12-character handle and nothing else (never another person's, never the
  asking browser, never a guess between two);
- the stored UA is long enough to name the browser at all.
"""
from __future__ import annotations

import sqlite3

import pytest

from ccsync_dashboard import auth, local_users, sessions
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.settings import Settings

CHROME_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
EDGE_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.2739.42")
SAFARI_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 "
                 "Safari/604.1")
SAFARI_MAC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/17.6 Safari/605.1.15")
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
CHROME_ANDROID = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36")
CHROME_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) CriOS/128.0.6613.98 Mobile/15E148 Safari/604.1")


def _client(ip, ua):
    return sessions.summarize_client(ip, ua)


# ---------------------------------------------------------------- describe_client

@pytest.mark.parametrize("ua,expected", [
    (CHROME_WIN, "Chrome, Windows"),
    (EDGE_WIN, "Edge, Windows"),
    (SAFARI_IPHONE, "Safari, iPhone"),
    (SAFARI_MAC, "Safari, macOS"),
    (FIREFOX_LINUX, "Firefox, Linux"),
    (CHROME_ANDROID, "Chrome, Android"),
    (CHROME_IOS, "Chrome, iPhone"),
    # Review round 2026-09-25: "Microsoft" contains "cros"; WSLg is Linux.
    ("Mozilla/5.0 (X11; Linux x86_64; Microsoft WSLg) Gecko/20100101 Firefox/130.0",
     "Firefox, Linux"),
    ("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36", "Chrome, ChromeOS"),
    ("Python-urllib/3.12", "python-urllib"),
    ("curl/8.4.0", "curl"),
    ("testclient", "a test client"),
    ("SomethingNobodyHasHeardOf/1.0", "Unknown browser"),
])
def test_describe_client_names_real_user_agents(ua, expected):
    got = sessions.describe_client(_client("100.64.3.21", ua))
    assert got == {"ip": "100.64.3.21", "browser": expected}


def test_describe_client_empty_and_missing():
    assert sessions.describe_client("") == {"ip": "", "browser": ""}
    assert sessions.describe_client(None) == {"ip": "", "browser": ""}
    # summarize_client writes "?" for an unknown peer, and nothing for no UA.
    assert sessions.describe_client(_client(None, None)) == {"ip": "", "browser": ""}
    assert sessions.describe_client(_client("10.0.0.5", "")) == {"ip": "10.0.0.5",
                                                                 "browser": ""}


def test_describe_client_on_a_row_cut_at_the_old_80_character_cap():
    """Rows written before 2026-09-25 were cut at 80 characters, inside
    "(KHTML, like Gecko)": the system is still named, the browser honestly not."""
    legacy = "100.64.3.21 " + CHROME_WIN[:80] + "..."
    assert sessions.describe_client(legacy) == {"ip": "100.64.3.21", "browser": "Windows"}


def test_describe_client_never_echoes_the_raw_user_agent():
    hostile = "<script>alert(1)</script> (evil)"
    got = sessions.describe_client(_client("1.2.3.4", hostile))
    assert got["browser"] == "Unknown browser"


def test_summarize_client_keeps_the_browser_token_now():
    stored = sessions.summarize_client("1.2.3.4", EDGE_WIN)
    assert "Edg/" in stored
    assert sessions.describe_client(stored)["browser"] == "Edge, Windows"
    # Still bounded: a client cannot make us store a novel.
    long_ua = "x" * 5000
    assert len(sessions.summarize_client("1.2.3.4", long_ua)) < 260


def test_describe_client_has_no_em_dash():
    for ua in (CHROME_WIN, SAFARI_IPHONE, "", "zzz", "python-urllib/3"):
        assert "—" not in sessions.describe_client(_client("1.1.1.1", ua))["browser"]


# ---------------------------------------------------------------- revoke_by_handle

@pytest.fixture
def store(tmp_path):
    path = tmp_path / "s.db"
    conn = dbmod.connect(path)
    dbmod.migrate(conn)
    conn.close()
    s = sessions.SessionStore(path)
    s.ensure_schema()
    return s


def _live(store, sid):
    return store.validate(sid) is not None


def test_revoke_by_handle_revokes_one_of_your_own(store):
    store.create("aaaaaaaaaaaa" + "1" * 52, "tchen", "1.1.1.1 x")
    store.create("bbbbbbbbbbbb" + "2" * 52, "tchen", "1.1.1.2 x")
    n = store.revoke_by_handle("tchen", "aaaaaaaaaaaa", by="self:tchen")
    assert n == 1
    assert not _live(store, "aaaaaaaaaaaa" + "1" * 52)
    assert _live(store, "bbbbbbbbbbbb" + "2" * 52)
    # Already signed out: 0, and the route says so.
    assert store.revoke_by_handle("tchen", "aaaaaaaaaaaa", by="self:tchen") == 0


def test_revoke_by_handle_never_touches_another_persons_session(store):
    """Same 12-character prefix, different person: invisible to this call."""
    theirs = "cccccccccccc" + "3" * 52
    store.create(theirs, "owen", "1.1.1.3 x")
    assert store.revoke_by_handle("tchen", "cccccccccccc", by="self:tchen") == 0
    assert _live(store, theirs)


def test_revoke_by_handle_username_is_case_insensitive(store):
    store.create("dddddddddddd" + "4" * 52, "tchen", "")
    assert store.revoke_by_handle("TChen", "dddddddddddd", by="self:tchen") == 1


def test_revoke_by_handle_refuses_the_current_session(store):
    mine = "eeeeeeeeeeee" + "5" * 52
    store.create(mine, "tchen", "")
    with pytest.raises(ValueError, match="current"):
        store.revoke_by_handle("tchen", "eeeeeeeeeeee", by="self:tchen", except_sid=mine)
    assert _live(store, mine)


def test_revoke_by_handle_refuses_ambiguity(store):
    a = "ffffffffffff" + "6" * 52
    b = "ffffffffffff" + "7" * 52
    store.create(a, "tchen", "")
    store.create(b, "tchen", "")
    with pytest.raises(ValueError, match="ambiguous"):
        store.revoke_by_handle("tchen", "ffffffffffff", by="self:tchen")
    assert _live(store, a) and _live(store, b)


@pytest.mark.parametrize("handle", ["", "abc", "AAAAAAAAAAAA", "%%%%%%%%%%%%",
                                    "____________", "aaaaaaaaaaaaa", None, 123])
def test_revoke_by_handle_malformed_handle_matches_nothing(store, handle):
    """A LIKE wildcard in a handle must never widen the match."""
    s = "aaaaaaaaaaaa" + "8" * 52
    store.create(s, "tchen", "")
    assert store.revoke_by_handle("tchen", handle, by="self:tchen") == 0
    assert _live(store, s)


def test_revoke_by_handle_ignores_an_already_revoked_twin(store):
    """A revoked row with the same prefix is not a second match."""
    gone = "abababababab" + "9" * 52
    live = "abababababab" + "0" * 52
    store.create(gone, "tchen", "")
    store.create(live, "tchen", "")
    store.revoke(gone, by="logout")
    assert store.revoke_by_handle("tchen", "abababababab", by="self:tchen") == 1
    assert not _live(store, live)


def test_revoke_by_handle_records_who(store, tmp_path):
    s = "121212121212" + "1" * 52
    store.create(s, "tchen", "")
    store.revoke_by_handle("tchen", "121212121212", by="self:tchen")
    conn = sqlite3.connect(store.db_path)
    row = conn.execute("SELECT revoked_by FROM auth_sessions WHERE sid=?", (s,)).fetchone()
    conn.close()
    assert row[0] == "self:tchen"


def test_session_handle_helpers():
    sid = "0123456789ab" + "c" * 52
    assert sessions.session_handle(sid) == "0123456789ab"
    assert sessions.is_session_handle("0123456789ab")
    assert not sessions.is_session_handle("0123456789aB")
    assert not sessions.is_session_handle(None)


# ---------------------------------------------------------------- admin_source

def test_admin_source_list_wins_on_every_method(tmp_path):
    for method in ("smb", "oidc", "local"):
        s = Settings(db_path=str(tmp_path / "a.db"), admin_users=frozenset({"owen"}),
                     auth_method=method)
        assert auth.admin_source(s, "owen") == "admin_list"
        assert auth.admin_source(s, "OWEN") == "admin_list"


def test_admin_source_local_role_only_on_local(tmp_path):
    path = tmp_path / "l.db"
    conn = dbmod.connect(path)
    dbmod.migrate(conn)
    local_users.create_user(conn, "mira", "a-long-enough-password", "admin")
    local_users.create_user(conn, "tchen", "a-long-enough-password", "editor")
    # A second admin, so disabling mira below is not refused as the last one.
    local_users.create_user(conn, "ana", "a-long-enough-password", "admin")
    conn.commit()
    local = Settings(db_path=str(path), admin_users=frozenset({"owen"}), auth_method="local")
    smb = Settings(db_path=str(path), admin_users=frozenset({"owen"}), auth_method="smb")
    assert auth.admin_source(local, "mira") == "local_role"
    assert auth.admin_source(local, "mira", conn) == "local_role"
    assert auth.admin_source(smb, "mira") == ""
    assert auth.admin_source(local, "tchen") == ""
    assert auth.admin_source(local, None) == ""
    assert auth.admin_source(local, "") == ""
    # A disabled local admin is not an admin, exactly as is_admin says.
    local_users.disable_user(conn, "mira", True)
    conn.commit()
    assert auth.admin_source(local, "mira") == ""
    assert auth.is_admin(local, "mira") is False
    conn.close()


def test_admin_source_agrees_with_is_admin(tmp_path):
    s = Settings(db_path=str(tmp_path / "a.db"), admin_users=frozenset({"owen"}))
    for name in ("owen", "tchen", "", None):
        assert bool(auth.admin_source(s, name)) == auth.is_admin(s, name)
