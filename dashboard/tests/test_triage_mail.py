"""The server triage agent's reply path (2026-09-24,
docs/SERVER_TRIAGE_AGENT.md section 3).

Pins: the three authentication checks, each failing ALONE (and the refusal is
a notice, never an answering email); the topmost Authentication-Results rule;
quote stripping; the digits-only parse; idempotency (the same Message-ID
twice, the same action twice, an expired reference); execution through the
BUTTON'S OWN FUNCTION (a stub proves the route's function was called, and a
real one proves its audit row); the confirmation text; the prose interpreter's
argv (no tools at all); and the IMAP poll against a fake server (the search is
the fence, handled mail is marked seen, somebody else's is left alone). No
test touches a real CLI, SMTP or IMAP server.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from email.message import EmailMessage

import pytest

from ccsync_dashboard import alerts, triage, triage_actions, triage_mail
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.settings import Settings

EM = chr(0x2014)
TAIPEI = dt.timezone(dt.timedelta(hours=8))
NOW = "2026-09-24T02:00:00+00:00"
LATER = "2026-09-27T02:00:00+00:00"          # past the 48 h reference
TOKEN = "AbCdEfGhIjKlMnOpQrStUv"
OWNER = "owner@example.com"
REPLY_TO = "owner+ccsync@example.com"
GOOD_AR = ("mx.google.com; dkim=pass header.i=@example.com header.s=google "
           "header.b=abc; spf=pass (google.com: domain of owner@example.com "
           "designates 1.2.3.4 as permitted sender) smtp.mailfrom=owner@example.com; "
           "dmarc=pass (p=NONE sp=NONE dis=NONE) header.from=example.com")


@pytest.fixture
def site(tmp_path, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "dash.db"))
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    alerts.set_settings(conn, {
        "alerts_sink": "smtp", "alerts_smtp_host": "smtp.gmail.com",
        "alerts_smtp_user": OWNER, "alerts_smtp_from": OWNER,
        "alerts_smtp_to": f"{OWNER}, second@example.com", "alerts_triage": "1",
        "alerts_triage_reply_to": REPLY_TO,
    }, "owen")
    conn.commit()
    monkeypatch.setattr(alerts, "_zone_or_utc", lambda _c: (TAIPEI, "Asia/Taipei"))
    # Prose goes to the model; no test here may reach a real one.
    monkeypatch.setattr(triage, "cli_gate", lambda c, s: ("", "no CLI in the suite"))
    yield settings, conn
    conn.close()


def seed_run(conn, actions=(("resume_breaker", {"editor": "ruskin", "machine": "DESKTOP-1"}),),
             token=TOKEN, expires="2026-09-26T02:00:00+00:00", run_id=1):
    conn.execute(
        "INSERT INTO triage_runs (id, started_at, finished_at, status, token_hash, "
        "token_expires_at, report_json, email_ok) VALUES (?, ?, ?, 'ok', ?, ?, ?, 1)",
        (run_id, NOW, NOW, hashlib.sha256(token.encode()).hexdigest(), expires,
         json.dumps({"subject": "[CC Sync] Server check: one computer stopped"})))
    for n, (name, params) in enumerate(actions, 1):
        conn.execute("INSERT INTO triage_actions (run_id, n, action, params_json, why, state) "
                     "VALUES (?, ?, ?, ?, '', 'offered')",
                     (run_id, n, name, json.dumps(params, sort_keys=True)))
    conn.commit()


def seed_machine(conn, editor="ruskin", machine="DESKTOP-1", tripped=True):
    conn.execute("INSERT INTO machines (editor_username, machine, platform, first_seen, "
                 "last_seen) VALUES (?, ?, 'windows', ?, ?)", (editor, machine, NOW, NOW))
    conn.execute("INSERT INTO machine_state (editor_username, machine, reported_at, verified, "
                 "breaker_tripped, guard_at) VALUES (?, ?, ?, 1, ?, ?)",
                 (editor, machine, NOW, int(tripped), NOW))
    conn.commit()


def reply(body="do 1", *, sender=OWNER, to=REPLY_TO, ar=(GOOD_AR,),
          message_id="<r1@mail.gmail.com>", token=TOKEN, subject=None) -> bytes:
    msg = EmailMessage()
    # Topmost first, as the receiving server prepends it.
    for header in ar:
        msg["Authentication-Results"] = header
    msg["From"] = f"Owner <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject or "Re: [CC Sync] Server check: one computer stopped"
    if message_id:
        msg["Message-ID"] = message_id
    quoted = ("\n\nOn Thu, 24 Sep 2026 at 06:01, CC Sync <owner@example.com>\nwrote:\n"
              "> [1] Resume proxy download on ruskin/DESKTOP-1\n"
              f"> Reference: CCT-{token}   (valid until 2026-09-26 10:00 Asia/Taipei)\n"
              if token else "")
    msg.set_content(body + quoted)
    return msg.as_bytes()


def handle(site, raw, **kw):
    settings, conn = site
    out = triage_mail.handle_message(conn, settings, raw, now=kw.pop("now", NOW), **kw)
    conn.commit()
    return out


def refused_notices(conn):
    return {r["subject"]: r for r in dbmod.open_notices(conn)
            if r["kind"] == triage_mail.REFUSED_KIND}


# ------------------------------------------------------------ authentication

def test_a_good_reply_is_acted_on(site):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    out = handle(site, reply())
    assert out["verdict"] == "acted" and out["mark_seen"]
    assert [o["state"] for o in out["outcomes"]] == ["done"]
    assert refused_notices(conn) == {}


@pytest.mark.parametrize("case", ["sender", "authentication", "reference"])
def test_each_check_failing_alone_refuses_without_an_answer(site, case):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    kwargs = {"sender": {"sender": "mallory@example.com"},
              "authentication": {"ar": ("mx.google.com; dkim=fail header.i=@example.com; "
                                        "dmarc=fail header.from=example.com",)},
              "reference": {"token": "NotARealTokenAtAll0000"}}[case]
    out = handle(site, reply(**kwargs))
    assert out["verdict"] == "refused"
    assert out["confirmation"] is None                 # no backscatter
    assert out["mark_seen"]
    notices = refused_notices(conn)
    assert list(notices) == [case]
    assert notices[case]["severity"] == "warn"
    assert "no answer was sent" in notices[case]["body"]
    # Nothing was done.
    assert conn.execute("SELECT state FROM triage_actions").fetchone()[0] == "offered"
    row = conn.execute("SELECT verdict, detail FROM triage_replies").fetchone()
    assert row["verdict"] == "refused" and row["detail"].startswith(case)


def test_only_the_topmost_authentication_results_counts(site):
    """A sender can write any header it likes BELOW the receiver's."""
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    out = handle(site, reply(ar=("mx.google.com; dkim=none; dmarc=none", GOOD_AR)))
    assert out["verdict"] == "refused"
    assert "authentication" in refused_notices(conn)


def test_no_authentication_results_at_all_fails_closed(site):
    out = handle(site, reply(ar=()))
    assert out["verdict"] == "refused"
    assert "added no Authentication-Results" in refused_notices(site[1])["authentication"]["body"]


def test_a_pass_for_another_domain_or_inside_a_comment_is_not_a_pass():
    import email as email_mod
    import email.policy

    def check(header):
        msg = email_mod.message_from_bytes(
            f"Authentication-Results: {header}\r\n\r\nx".encode(), policy=email.policy.default)
        return triage_mail.auth_results_pass(msg, "example.com")[0]

    assert check(GOOD_AR)
    assert check("mx.google.com; dmarc=pass header.from=EXAMPLE.com")
    assert not check("mx.google.com; dkim=pass header.d=attacker.test")
    assert not check("mx.google.com; dkim=fail (dkim=pass header.d=example.com) header.d=example.com")


def test_from_is_compared_case_folded_against_the_to_list(site):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    assert handle(site, reply(sender="Second@Example.COM"))["verdict"] == "acted"


def test_mail_not_addressed_to_the_reply_address_is_skipped_and_left_alone(site):
    settings, conn = site
    seed_run(conn)
    raw = reply(to="xowner+ccsync@example.com")          # IMAP TO is a substring match
    out = handle(site, raw)
    assert out == {"verdict": "skipped", "mark_seen": False, "confirmation": None}
    assert refused_notices(conn) == {}
    # And every later poll leaves it alone too.
    assert handle(site, raw)["mark_seen"] is False


# --------------------------------------------------------- reading the reply

def test_quote_stripping_keeps_only_the_replys_own_words():
    gmail = ("do 1 and 3\n\nOn Thu, 24 Sep 2026 at 06:01, CC Sync <a@b.c>\nwrote:\n"
             "> [1] Resume\n> Reference: CCT-x")
    assert triage_mail.strip_quotes(gmail) == "do 1 and 3"
    assert triage_mail.strip_quotes("yes the first one\nOn Thu, Sep 24 wrote:\nold") == \
        "yes the first one"
    assert triage_mail.strip_quotes("2 please\n> quoted\nmore") == "2 please"
    assert triage_mail.strip_quotes("1\n-----Original Message-----\nFrom: x") == "1"
    assert triage_mail.strip_quotes("3\n-- \nAlex") == "3"


@pytest.mark.parametrize("text,expected", [
    ("do 1 and 3", [1, 3]), ("1, 2", [1, 2]), ("2", [2]), ("Do 1 & 2.", [1, 2]),
    ("1 2 3", [1, 2, 3]), ("all", "all"), ("Do all", "all"), ("none", []),
    ("nothing", []), ("please resume ruskin", None), ("do 1 but not 2", None),
    ("", None),
])
def test_the_digits_only_parse(text, expected):
    assert triage_mail.parse_simple(text) == expected


def test_prose_without_a_cli_is_not_understood_and_nothing_runs(site):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    out = handle(site, reply("yes go ahead with the ruskin one"))
    assert out["verdict"] == "acted" and out["outcomes"] == []
    subject, body = out["confirmation"]
    assert "did not choose any of the offered actions" in body
    assert "Not clear from your reply: the reply is not a list of numbers" in body
    assert conn.execute("SELECT state FROM triage_actions").fetchone()[0] == "offered"


def test_prose_goes_to_a_tool_less_model_call(site, monkeypatch):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    monkeypatch.setattr(triage, "cli_gate", lambda c, s: ("/opt/claude", ""))
    calls = []

    def spawn(argv, prompt, cwd, env, timeout):
        calls.append((argv, prompt, timeout))
        answer = {"do": [1, 9], "skip": [], "unclear": f"which {EM} one?", "note": ""}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(
            {"type": "result", "is_error": False, "result": json.dumps(answer)}), stderr="")

    monkeypatch.setattr(triage, "_spawn", spawn)
    out = handle(site, reply("yes, resume the ruskin one"))
    [(argv, prompt, timeout)] = calls
    assert argv[argv.index("--model") + 1] == "sonnet"
    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    for tool in ("Bash", "Read", "Grep", "Glob", "Write", "Edit", "WebFetch", "Task"):
        assert tool in denied
    assert "--allowedTools" not in argv
    assert timeout == 180
    assert "yes, resume the ruskin one" in prompt and "[1] Resume proxy download" in prompt
    assert [(o["n"], o["state"]) for o in out["outcomes"]] == [(1, "done"), (9, "not_offered")]
    assert EM not in out["confirmation"][1]


# -------------------------------------------------------------- idempotency

def test_the_same_message_id_twice_acts_once(site, monkeypatch):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    calls = []
    monkeypatch.setattr(dbmod, "request_lane_b_resume",
                        lambda c, e, m, by, now: calls.append((e, m, by)) or True)
    assert handle(site, reply())["verdict"] == "acted"
    again = handle(site, reply())
    assert again["verdict"] == "duplicate" and again["confirmation"] is None
    assert len(calls) == 1


def test_the_same_action_chosen_twice_runs_once(site, monkeypatch):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    calls = []
    monkeypatch.setattr(dbmod, "request_lane_b_resume",
                        lambda c, e, m, by, now: calls.append(by) or True)
    first = handle(site, reply("1", message_id="<a@x>"))
    second = handle(site, reply("do 1", message_id="<b@x>"))
    assert first["outcomes"][0]["state"] == "done"
    assert second["outcomes"][0]["state"] == "already"
    assert "already done" in second["outcomes"][0]["detail"]
    assert len(calls) == 1
    row = conn.execute("SELECT state, reply_message_id FROM triage_actions").fetchone()
    assert tuple(row) == ("done", "<a@x>")


def test_an_expired_reference_is_refused(site):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    out = handle(site, reply(), now=LATER)
    assert out["verdict"] == "refused"
    assert "has expired" in refused_notices(conn)["reference"]["body"]
    triage.expire_actions(conn, LATER)
    assert conn.execute("SELECT state FROM triage_actions").fetchone()[0] == "expired"


# ---------------------------------------------------------------- execution

def test_execution_goes_through_the_buttons_own_function(site, monkeypatch):
    """resume_breaker is FLEET [ RESUME ]: the route calls
    db.request_lane_b_resume, and so must the reply, with the reply's actor."""
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    calls = []
    monkeypatch.setattr(dbmod, "request_lane_b_resume",
                        lambda c, e, m, by, now: calls.append((e, m, by)) or True)
    handle(site, reply())
    assert calls == [("ruskin", "DESKTOP-1", f"triage-email:{OWNER}")]


def test_a_real_action_writes_the_buttons_audit_row(site):
    settings, conn = site
    notice_id = dbmod.notice(conn, "machine_disk_low", "warn", "ruskin/DESKTOP-1",
                             body="b", fix="f")
    seed_run(conn, actions=(("dismiss_notice", {"notice_id": notice_id}),))
    out = handle(site, reply("1"))
    assert out["outcomes"][0]["state"] == "done"
    audit = conn.execute("SELECT actor, action FROM fleet_audit "
                         "WHERE action='notice.dismiss'").fetchone()
    assert tuple(audit) == (f"triage-email:{OWNER}", "notice.dismiss")


def test_revalidation_at_reply_time_refuses_a_stale_action(site):
    """The breaker cleared between the email and the reply."""
    settings, conn = site
    seed_machine(conn, tripped=False)
    seed_run(conn)
    out = handle(site, reply())
    [o] = out["outcomes"]
    assert o["state"] == "refused" and "nothing to resume" in o["detail"]
    row = conn.execute("SELECT state, result FROM triage_actions").fetchone()
    assert row["state"] == "refused" and "nothing to resume" in row["result"]
    # Refused is final: choosing it again does not run it.
    again = handle(site, reply(message_id="<again@x>"))
    assert again["outcomes"][0]["state"] == "already"


def test_a_failing_action_rolls_back_alone(site, monkeypatch):
    settings, conn = site
    seed_machine(conn)
    notice_id = dbmod.notice(conn, "machine_disk_low", "warn", "s", body="b", fix="f")
    seed_run(conn, actions=(
        ("resume_breaker", {"editor": "ruskin", "machine": "DESKTOP-1"}),
        ("dismiss_notice", {"notice_id": notice_id}),
    ))

    def boom(*_a, **_kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(dbmod, "request_lane_b_resume", boom)
    out = handle(site, reply("1 and 2"))
    assert [(o["n"], o["state"]) for o in out["outcomes"]] == [(1, "failed"), (2, "done")]
    states = dict(conn.execute("SELECT n, state FROM triage_actions").fetchall())
    assert states == {1: "failed", 2: "done"}


def test_all_runs_every_offered_action(site):
    settings, conn = site
    seed_machine(conn)
    notice_id = dbmod.notice(conn, "machine_disk_low", "warn", "s", body="b", fix="f")
    seed_run(conn, actions=(
        ("resume_breaker", {"editor": "ruskin", "machine": "DESKTOP-1"}),
        ("dismiss_notice", {"notice_id": notice_id}),
    ))
    out = handle(site, reply("all"))
    assert [o["state"] for o in out["outcomes"]] == ["done", "done"]


def test_nudge_collector_calls_the_registered_collectors_nudge(site, monkeypatch):
    settings, conn = site
    nudged = []

    class Collector:
        def nudge(self):
            nudged.append(True)

    monkeypatch.setattr(triage_actions, "_COLLECTOR", Collector())
    seed_run(conn, actions=(("nudge_collector", {}),))
    assert handle(site, reply("1"))["outcomes"][0]["state"] == "done"
    assert nudged == [True]


# ------------------------------------------------------------- confirmation

def test_the_confirmation_lists_each_outcome(site):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn, actions=(
        ("resume_breaker", {"editor": "ruskin", "machine": "DESKTOP-1"}),
        ("cancel_job", {"job_id": 5}),
    ))
    out = handle(site, reply("1, 2, 7"))
    subject, body = out["confirmation"]
    assert subject == "Re: [CC Sync] Server check: one computer stopped"
    assert "[1] Resume proxy download on ruskin/DESKTOP-1: done - asked" in body
    assert "[2] Cancel fleet job #5: refused - there is no job #5" in body
    assert "[7]: not understood - that number was not offered in this check" in body
    assert f"Reference: CCT-{TOKEN}" in body and "valid until 2026-09-26 10:00 Asia/Taipei" in body
    assert EM not in body


# --------------------------------------------------------------------- poll

class FakeIMAP:
    instances: list = []
    messages: dict = {}

    def __init__(self, host, port, ssl_context=None, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.ssl_context = ssl_context
        self.calls: list = []
        FakeIMAP.instances.append(self)

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def select(self, box):
        self.calls.append(("select", box))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.calls.append(("search", criteria))
        return "OK", [b" ".join(FakeIMAP.messages)]

    def fetch(self, num, what):
        self.calls.append(("fetch", num, what))
        return "OK", [(b"1 (BODY[] {n}", FakeIMAP.messages[num]), b")"]

    def store(self, num, op, flags):
        self.calls.append(("store", num, op, flags))

    def logout(self):
        self.calls.append(("logout",))


def test_the_poll_is_fenced_marks_what_it_handled_and_confirms(site, monkeypatch):
    settings, conn = site
    seed_machine(conn)
    seed_run(conn)
    alerts.set_password(settings, "app-password-1234")
    FakeIMAP.instances = []
    FakeIMAP.messages = {b"11": reply(message_id="<ok@x>"),
                         b"12": reply(to="xowner+ccsync@example.com", message_id="<other@x>")}
    monkeypatch.setattr(triage_mail, "_imap_class", lambda: FakeIMAP)
    sent = []
    monkeypatch.setattr(alerts, "_transmit",
                        lambda c, s, subject, text, *, label="", reply_to="": sent.append(
                            (subject, text, label, reply_to))
                        or {"ok": True, "sink": "smtp", "sent_to": OWNER, "detail": "sent"})
    out = triage_mail.poll(settings, now=NOW)
    assert out["ok"] and out["handled"] == 2
    [imap] = FakeIMAP.instances
    assert (imap.host, imap.port) == ("imap.gmail.com", 993)
    assert imap.ssl_context is not None
    assert ("login", OWNER, "app-password-1234") in imap.calls
    assert ("select", "INBOX") in imap.calls
    search = next(c for c in imap.calls if c[0] == "search")[1]
    assert search == ("UNSEEN", "TO", f'"{REPLY_TO}"', "SINCE", "22-Sep-2026")
    stores = [c for c in imap.calls if c[0] == "store"]
    assert stores == [("store", b"11", "+FLAGS", "\\Seen")]     # 12 is not ours
    assert all(c[2] == "(BODY.PEEK[])" for c in imap.calls if c[0] == "fetch")
    [(subject, text, label, reply_to)] = sent
    assert label == "triage_reply" and reply_to == REPLY_TO
    assert subject.startswith("Re: [CC Sync] Server check")
    assert dbmod.last_alert_at(conn, triage.KIND_REPLY, ok_only=True)
    # A confirmation never retires a scheduled slot.
    assert dbmod.last_alert_at(conn, triage.KIND_TRIAGE, ok_only=False) is None
    assert dbmod.meta_get_json(conn, triage_mail.META_POLL)["ok"]
    assert "app-password-1234" not in json.dumps(dbmod.meta_get_json(conn, triage_mail.META_POLL))


def test_the_poll_does_nothing_when_replies_are_off(site, monkeypatch):
    settings, conn = site
    alerts.set_settings(conn, {"alerts_triage_reply_to": ""}, "owen")
    conn.commit()
    monkeypatch.setattr(triage_mail, "_imap_class",
                        lambda: pytest.fail("no IMAP with replies off"))
    assert triage_mail.poll(settings, now=NOW) == {"disabled": True}
    assert dbmod.meta_get(conn, triage_mail.META_POLL) is None


def test_a_login_failure_is_recorded_without_the_password(site, monkeypatch):
    import imaplib

    settings, conn = site
    alerts.set_password(settings, "app-password-1234")

    class Refusing(FakeIMAP):
        def login(self, user, password):
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    monkeypatch.setattr(triage_mail, "_imap_class", lambda: Refusing)
    out = triage_mail.poll(settings, now=NOW)
    assert not out["ok"] and "AUTHENTICATIONFAILED" in out["detail"]
    assert "app-password-1234" not in out["detail"]
