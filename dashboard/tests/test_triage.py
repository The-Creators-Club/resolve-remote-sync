"""The server triage agent's scheduled run (2026-09-24,
docs/SERVER_TRIAGE_AGENT.md sections 2, 4 and 5).

Pins: the durable schedule (slots, a restart, the backoff, the zone), the
evidence bundle (a raising reader is a section, never a failed run; the
scrub), the argv (read-only tools, never Bash, never a shell), parsing and
validating the model's answer (a bad action is dropped and said), the
fallback email when the CLI fails, the report body (the token footer, no em
dash), the one-at-a-time machinery, the settings validation, the Reply-To
header and the SERVER CHECK block. No test touches a real CLI, SMTP or IMAP
server: `triage._spawn`, `alerts._transmit` / `alerts._smtp_class` and
`triage._start_thread` are the seams.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, auth, triage, triage_actions, triage_mail
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

EM = chr(0x2014)
TAIPEI = dt.timezone(dt.timedelta(hours=8))
SECRET = "s"


def _utc(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)


def iso_taipei(y, mo, d, h, mi=0) -> str:
    return dt.datetime(y, mo, d, h, mi, tzinfo=TAIPEI).astimezone(dt.timezone.utc).isoformat()


@pytest.fixture
def site(tmp_path, monkeypatch):
    """(settings, conn) on a migrated database, the check on, mail as the
    channel, the zone pinned to +08:00 (this venv has no tzdata; the
    container resolves Asia/Taipei itself)."""
    settings = Settings(db_path=str(tmp_path / "dash.db"))
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    alerts.set_settings(conn, {
        "alerts_sink": "smtp", "alerts_smtp_host": "smtp.gmail.com",
        "alerts_smtp_user": "owner@example.com", "alerts_smtp_from": "owner@example.com",
        "alerts_smtp_to": "owner@example.com", "alerts_triage": "1",
        "alerts_triage_hours": "6,18",
        "alerts_triage_reply_to": "owner+ccsync@example.com",
    }, "owen")
    conn.commit()
    monkeypatch.setattr(alerts, "_zone_or_utc", lambda _c: (TAIPEI, "Asia/Taipei"))
    yield settings, conn
    conn.close()


@pytest.fixture
def sent(monkeypatch):
    """Every message the run hands to the sink, and never a network."""
    out: list[dict] = []

    def fake(conn, settings, subject, text, *, label="", reply_to=""):
        out.append({"subject": subject, "text": text, "label": label, "reply_to": reply_to})
        return {"ok": True, "sink": "smtp", "sent_to": "owner@example.com", "detail": "sent"}

    monkeypatch.setattr(alerts, "_transmit", fake)
    return out


def cli_reply(report: dict | str, is_error: bool = False) -> str:
    result = report if isinstance(report, str) else json.dumps(report)
    return json.dumps({"type": "result", "is_error": is_error, "result": result,
                       "modelUsage": {"claude-opus-5-5": {}}})


@pytest.fixture
def fake_cli(monkeypatch):
    """The CLI gate says yes and `_spawn` answers with whatever `answer`
    holds; every call is recorded."""
    calls: list[dict] = []
    answer = {"stdout": cli_reply({"subject": "all clear", "headline": "Nothing needs you.",
                                   "all_clear": True, "findings": [], "actions": []}),
              "returncode": 0, "stderr": "", "raise": None}
    monkeypatch.setattr(triage, "cli_gate", lambda conn, settings: ("/opt/claude/bin/claude", ""))

    def spawn(argv, prompt, cwd, env, timeout):
        calls.append({"argv": list(argv), "prompt": prompt, "cwd": cwd, "env": env,
                      "timeout": timeout,
                      "evidence": (Path(cwd) / "evidence.json").read_text(encoding="utf-8")
                      if (Path(cwd) / "evidence.json").exists() else None})
        if answer["raise"] is not None:
            raise answer["raise"]
        return subprocess.CompletedProcess(argv, answer["returncode"],
                                           stdout=answer["stdout"], stderr=answer["stderr"])

    monkeypatch.setattr(triage, "_spawn", spawn)
    return calls, answer


def seed_machine(conn, editor="ruskin", machine="DESKTOP-1", platform="windows",
                 version="0.9.74", tripped=None):
    now = "2026-09-24T00:00:00+00:00"
    conn.execute("INSERT INTO machines (editor_username, machine, platform, first_seen, "
                 "last_seen) VALUES (?, ?, ?, ?, ?)", (editor, machine, platform, now, now))
    conn.execute("INSERT INTO machine_state (editor_username, machine, reported_at, verified, "
                 "platform, companion_version, breaker_tripped, guard_at) "
                 "VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                 (editor, machine, now, platform, version,
                  None if tripped is None else int(tripped),
                  None if tripped is None else now))
    conn.commit()


# ------------------------------------------------------------------ schedule

def test_previous_slot_is_the_latest_hour_at_or_before_now_in_the_zone():
    hours = [6, 18]
    # 05:59 Taipei: yesterday's 18:00.
    got = triage.previous_slot(dt.datetime(2026, 9, 24, 5, 59, tzinfo=TAIPEI), TAIPEI, hours)
    assert got == dt.datetime(2026, 9, 23, 18, 0, tzinfo=TAIPEI).astimezone(dt.timezone.utc)
    # 06:00 exactly is the 06:00 slot.
    got = triage.previous_slot(dt.datetime(2026, 9, 24, 6, 0, tzinfo=TAIPEI), TAIPEI, hours)
    assert got == _utc(2026, 9, 23, 22)
    # 17:59 is still the morning's.
    got = triage.previous_slot(dt.datetime(2026, 9, 24, 17, 59, tzinfo=TAIPEI), TAIPEI, hours)
    assert got == _utc(2026, 9, 23, 22)


def test_the_zone_moves_the_slot():
    """The same instant is past 06:00 in Taipei and not in UTC."""
    instant = _utc(2026, 9, 24, 0, 30)          # 08:30 Taipei, 00:30 UTC
    assert triage.previous_slot(instant, TAIPEI, [6, 18]) == _utc(2026, 9, 23, 22)
    assert triage.previous_slot(instant, dt.timezone.utc, [6, 18]) == _utc(2026, 9, 23, 18)


def test_due_is_off_when_the_check_is_off_or_there_is_no_channel(site):
    settings, conn = site
    now = iso_taipei(2026, 9, 24, 6, 5)
    assert triage.triage_due(conn, now)
    alerts.set_settings(conn, {"alerts_sink": "none"}, "owen")
    assert not triage.triage_due(conn, now)
    alerts.set_settings(conn, {"alerts_sink": "smtp", "alerts_triage": "0"}, "owen")
    assert not triage.triage_due(conn, now)


def test_a_sent_report_retires_its_slot_and_a_restart_does_not_resend(site):
    settings, conn = site
    dbmod.record_alert(conn, triage.KIND_TRIAGE, "server check", "o", True, "sent",
                       iso_taipei(2026, 9, 24, 6, 2))
    conn.commit()
    # "six restarts do not run it six times": every later look before 18:00.
    for minute in (3, 30):
        assert not triage.triage_due(conn, iso_taipei(2026, 9, 24, 7, minute))
    assert not triage.triage_due(conn, iso_taipei(2026, 9, 24, 17, 59))
    assert triage.triage_due(conn, iso_taipei(2026, 9, 24, 18, 0))


def test_a_container_down_at_the_slot_runs_it_late(site):
    settings, conn = site
    dbmod.record_alert(conn, triage.KIND_TRIAGE, "server check", "o", True, "sent",
                       iso_taipei(2026, 9, 23, 18, 1))
    conn.commit()
    assert triage.triage_due(conn, iso_taipei(2026, 9, 24, 11, 40))


def test_a_failed_send_backs_off_then_retries(site):
    settings, conn = site
    dbmod.record_alert(conn, triage.KIND_TRIAGE, "server check", "", False, "refused",
                       iso_taipei(2026, 9, 24, 6, 1))
    conn.commit()
    assert not triage.triage_due(conn, iso_taipei(2026, 9, 24, 6, 5))
    assert triage.triage_due(conn, iso_taipei(2026, 9, 24, 6, 12))


# -------------------------------------------------------------------- bundle

def test_a_raising_reader_is_a_section_error_not_a_failed_bundle(site, monkeypatch):
    settings, conn = site
    from ccsync_dashboard import invariants

    def boom(_conn):
        raise RuntimeError("the invariant table is on fire")

    monkeypatch.setattr(invariants, "page_view", boom)
    bundle = triage.build_bundle(conn, settings, "2026-09-24T00:00:00+00:00")
    assert bundle["invariants"] == {"error": "RuntimeError: the invariant table is on fire"}
    for section in ("open_notices", "alert_log_48h", "collector", "fleet", "transfers",
                    "jobs", "packages", "previous_run"):
        assert section in bundle and not (isinstance(bundle[section], dict)
                                          and "error" in bundle[section]), section


def test_the_scrub_removes_keys_and_secret_shaped_values():
    bundle = {
        "fleet": {"editors": [{"machine": "M", "report_token": "abcdef123456",
                               "note": "key sk-ant-api03-ABCDEFGH1234 leaked"}]},
        "smtp_password": "hunter2hunter2",
        "api_key": "plain", "nested": {"Secret": {"deep": "x"}},
        "text": "fleet cred cce1.eyJhbGciOi.sig and a gh token ghp_ABCdef123",
        "harmless": "sha256 0123abcd",
    }
    out = triage.scrub(bundle)
    for leaked in ("abcdef123456", "sk-ant-api03", "hunter2", "plain", '"deep"',
                   "cce1.eyJ", "ghp_ABC"):
        assert leaked not in out, leaked
    data = json.loads(out)
    assert data["smtp_password"] == triage.REDACTED
    assert data["fleet"]["editors"][0]["machine"] == "M"
    assert data["harmless"] == "sha256 0123abcd"


def test_the_bundle_never_reads_the_secrets_directory(site, fake_cli, sent):
    settings, conn = site
    alerts.set_password(settings, "the-smtp-app-password")
    triage.run(settings, now=iso_taipei(2026, 9, 24, 6, 1))
    calls, _ = fake_cli
    assert "the-smtp-app-password" not in calls[0]["evidence"]
    assert "the-smtp-app-password" not in calls[0]["prompt"]


# ---------------------------------------------------------------------- argv

def test_the_argv_is_read_only_and_never_a_shell(site, fake_cli, sent):
    settings, conn = site
    triage.run(settings, now=iso_taipei(2026, 9, 24, 6, 1))
    calls, _ = fake_cli
    assert len(calls) == 1
    argv = calls[0]["argv"]
    assert isinstance(argv, list) and argv[0] == "/opt/claude/bin/claude"
    assert argv[1:4] == ["-p", "--output-format", "json"]
    allowed = argv[argv.index("--allowedTools") + 1]
    assert allowed == "Read,Grep,Glob"
    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    for tool in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch",
                 "WebSearch", "Task"):
        assert tool in denied
    assert "Bash" not in allowed
    assert argv[argv.index("--model") + 1] == "opus"          # the family alias, CR-309
    package_dir = Path(argv[argv.index("--add-dir") + 1])
    assert (package_dir / "triage.py").is_file()
    # The prompt goes on stdin, the evidence file is in the cwd, the model
    # is told the catalogue.
    assert Path(calls[0]["cwd"]).name.isdigit()
    assert json.loads(calls[0]["evidence"])["generated_at"]
    assert "resume_breaker(editor: str, machine: str)" in calls[0]["prompt"]
    assert calls[0]["timeout"] == 20 * 60


# ----------------------------------------------------------- parse / validate

def test_parse_report_reads_the_envelope_and_a_fenced_block():
    inner = 'Here you go:\n```json\n{"subject": "x", "findings": []}\n```\nthanks'
    assert triage.parse_report(cli_reply(inner)) == {"subject": "x", "findings": []}
    assert triage.parse_report('{"subject": "bare"}') == {"subject": "bare"}
    with pytest.raises(triage.TriageError):
        triage.parse_report(cli_reply("I could not decide."))
    with pytest.raises(triage.TriageError, match="reported an error"):
        triage.parse_report(cli_reply("API Error 529", is_error=True))


def test_bad_actions_are_dropped_with_their_reason(site):
    settings, conn = site
    seed_machine(conn, tripped=True)
    offered, dropped = triage.validate_actions(conn, settings, [
        {"n": 1, "action": "resume_breaker",
         "params": {"editor": "RUSKIN", "machine": "DESKTOP-1"}, "why": "stale trip"},
        {"n": 2, "action": "rm_rf", "params": {}},
        {"n": 3, "action": "resume_breaker", "params": {"editor": "ruskin", "machine": "NOPE"}},
        {"n": 1, "action": "nudge_collector", "params": {}},
        {"n": 4, "action": "cancel_job", "params": {"job_id": True}},
        {"n": 5, "action": "request_diagnostics",
         "params": {"editor": "ruskin", "machine": "DESKTOP-1", "shell": "ls"}},
        {"n": 6, "action": "resume_breaker",
         "params": {"editor": "ruskin", "machine": "DESKTOP-1"}},
    ])
    assert [(a["n"], a["action"], a["params"]) for a in offered] == [
        (1, "resume_breaker", {"editor": "ruskin", "machine": "DESKTOP-1"})]
    text = "\n".join(dropped)
    assert "'rm_rf' is not an action a reply can carry out" in text
    assert "no computer 'NOPE'" in text
    assert "number 1 was already used" in text
    assert "job_id" in text
    assert "does not take: shell" in text
    assert "already offered" in text


# --------------------------------------------------------- the report email

REPORT = {
    "subject": f"one computer stopped {EM} ruskin",
    "headline": f"Proxy download stopped on ruskin {EM} the trip looks stale.",
    "all_clear": False,
    "findings": [{"title": "Proxy download stopped", "severity": "error",
                  "evidence": "breaker_tripped since 03:00", "suggestion": "resume it",
                  "action_refs": [1], "code_fix_prompt": "Look at lane_guard.py\nand fix X"}],
    "actions": [{"n": 1, "action": "resume_breaker",
                 "params": {"editor": "ruskin", "machine": "DESKTOP-1"},
                 "why": f"the NAS tree is intact {EM} nothing was deleted"},
                {"n": 2, "action": "cancel_job", "params": {"job_id": 999}}],
}


def test_the_report_email_has_the_token_footer_and_no_em_dash(site, fake_cli, sent):
    settings, conn = site
    seed_machine(conn, tripped=True)
    calls, answer = fake_cli
    answer["stdout"] = cli_reply(REPORT)
    result = triage.run(settings, now=iso_taipei(2026, 9, 24, 6, 1))
    assert result["status"] == "ok" and result["email_ok"]
    [mail] = sent
    assert mail["subject"].startswith("[CC Sync] Server check: ")
    assert mail["reply_to"] == "owner+ccsync@example.com"
    body = mail["text"]
    assert EM not in body and EM not in mail["subject"]
    assert "[1] Resume proxy download on ruskin/DESKTOP-1 - the NAS tree is intact" in body
    assert 'To carry any of these out, reply to this email, e.g. "do 1 and 3".' in body
    assert "Reference: CCT-" in body and "each action runs once" in body
    assert "valid until 2026-09-26 06:01 Asia/Taipei" in body
    # The bad suggestion is SAID, not offered.
    assert "Suggested but not offered:" in body and "there is no job #999" in body
    assert "     Look at lane_guard.py" in body
    # The ledger: one offered action, the token only as a hash, one ok row.
    token = body.split("Reference: CCT-")[1].split()[0]
    row = conn.execute("SELECT * FROM triage_runs").fetchone()
    assert token not in (row["token_hash"] or "") and len(row["token_hash"]) == 64
    assert row["status"] == "ok" and row["email_ok"] == 1
    acts = conn.execute("SELECT n, action, state FROM triage_actions").fetchall()
    assert [tuple(a) for a in acts] == [(1, "resume_breaker", "offered")]
    assert dbmod.last_alert_at(conn, triage.KIND_TRIAGE, ok_only=True)


def test_an_all_clear_still_sends(site, fake_cli, sent):
    settings, conn = site
    triage.run(settings, now=iso_taipei(2026, 9, 24, 6, 1))
    [mail] = sent
    assert "Nothing needs you." in mail["text"]
    assert "Reference: CCT-" not in mail["text"]


def test_no_reply_address_says_replies_are_off(site, fake_cli, sent):
    settings, conn = site
    seed_machine(conn, tripped=True)
    alerts.set_settings(conn, {"alerts_triage_reply_to": ""}, "owen")
    conn.commit()
    fake_cli[1]["stdout"] = cli_reply(REPORT)
    triage.run(settings, now=iso_taipei(2026, 9, 24, 6, 1))
    assert "Replies are switched off on this server" in sent[0]["text"]
    assert "Reference: CCT-" not in sent[0]["text"]


# ---------------------------------------------------------------- fallback

@pytest.mark.parametrize("failure", ["exit", "timeout", "garbage", "gate"])
def test_a_cli_failure_still_sends_a_fallback_made_in_code(site, fake_cli, sent,
                                                           monkeypatch, failure):
    settings, conn = site
    dbmod.notice(conn, "machine_disk_low", "warn", "ruskin/DESKTOP-1", body="b", fix="f")
    conn.commit()
    calls, answer = fake_cli
    if failure == "exit":
        answer.update(returncode=1, stderr="Invalid API key", stdout="")
    elif failure == "timeout":
        answer["raise"] = subprocess.TimeoutExpired(["claude"], 1200)
    elif failure == "garbage":
        answer["stdout"] = cli_reply("sorry, no JSON today")
    else:
        monkeypatch.setattr(triage, "cli_gate",
                            lambda c, s: ("", "Claude Code is not installed on this server"))
    result = triage.run(settings, now=iso_taipei(2026, 9, 24, 6, 1))
    assert result["status"] == "fallback"
    [mail] = sent
    assert mail["subject"] == "[CC Sync] Server check: the analysis could not run"
    assert mail["text"].startswith("The server check could not run its analysis: ")
    assert "an editor's computer is nearly out of room for footage: ruskin/DESKTOP-1" in mail["text"]
    assert "Background jobs failing: none" in mail["text"]
    assert EM not in mail["text"]
    assert conn.execute("SELECT COUNT(*) FROM triage_actions").fetchone()[0] == 0
    assert dbmod.last_alert_at(conn, triage.KIND_TRIAGE, ok_only=True)
    if failure == "gate":
        assert calls == []


def test_a_crash_inside_the_run_is_still_an_email(site, fake_cli, sent, monkeypatch):
    settings, conn = site

    def boom(*_a, **_kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(triage, "scrub", boom)
    result = triage.run(settings, now=iso_taipei(2026, 9, 24, 6, 1))
    assert result["status"] == "failed"
    [mail] = sent
    assert mail["subject"] == "[CC Sync] Server check: the check failed"
    assert "RuntimeError: disk full" in mail["text"]
    assert conn.execute("SELECT status FROM triage_runs").fetchone()[0] == "failed"
    assert dbmod.meta_get(conn, triage.META_RUNNING) is None


# ------------------------------------------------------------ the machinery

@pytest.fixture
def threads(monkeypatch):
    started: list = []
    monkeypatch.setattr(triage, "_start_thread",
                        lambda target, name, *args: started.append((name, target, args)))
    monkeypatch.setattr(triage, "_POLLER", None)
    yield started
    if triage._RUN_LOCK.locked():
        triage._RUN_LOCK.release()


def test_maybe_start_decides_and_starts_one_run_at_a_time(site, threads):
    settings, conn = site
    now = iso_taipei(2026, 9, 24, 6, 5)
    first = triage.maybe_start(settings, now, conn=conn)
    assert first["started"]
    names = [n for n, _t, _a in threads]
    assert names.count("dash-triage-run") == 1
    assert "dash-triage-replies" in names
    assert dbmod.meta_get(conn, triage.META_RUNNING) == now
    # Still due (nothing sent yet), but one is running.
    again = triage.maybe_start(settings, now, conn=conn)
    assert not again["started"] and "already running" in again["why"]
    assert [n for n, _t, _a in threads].count("dash-triage-run") == 1


def test_a_stale_running_row_does_not_block(site, threads):
    settings, conn = site
    dbmod.meta_set(conn, triage.META_RUNNING, iso_taipei(2026, 9, 24, 3, 0))
    conn.commit()
    assert triage.maybe_start(settings, iso_taipei(2026, 9, 24, 6, 5), conn=conn)["started"]


def test_off_starts_nothing_and_still_stamps_the_refused_kind(site, threads):
    settings, conn = site
    alerts.set_settings(conn, {"alerts_triage": "0"}, "owen")
    conn.commit()
    now = iso_taipei(2026, 9, 24, 6, 5)
    assert triage.maybe_start(settings, now, conn=conn) == {"started": False, "why": "off"}
    assert threads == []
    assert triage_mail.REFUSED_KIND in dbmod.notice_check_times(conn)
    assert triage_mail.REFUSED_KIND in dbmod.NOTICE_KINDS


def test_run_now_refuses_when_off_or_without_a_channel(site, threads):
    settings, conn = site
    alerts.set_settings(conn, {"alerts_sink": "none"}, "owen")
    ok, why = triage.start_run(settings, conn)
    assert not ok and "no alert channel" in why
    alerts.set_settings(conn, {"alerts_sink": "smtp", "alerts_triage": "0"}, "owen")
    ok, why = triage.start_run(settings, conn)
    assert not ok and "off" in why
    alerts.set_settings(conn, {"alerts_triage": "1"}, "owen")
    ok, _why = triage.start_run(settings, conn)
    assert ok


def test_alerts_run_cycle_hands_over_to_maybe_start(site, monkeypatch):
    settings, conn = site
    seen = []
    monkeypatch.setattr(alerts, "scan", lambda *_a, **_kw: [])
    monkeypatch.setattr(triage, "maybe_start",
                        lambda s, now, conn=None: seen.append(now) or {"started": False})
    alerts.run_cycle(conn, settings, "2026-09-24T00:00:00+00:00")
    assert seen == ["2026-09-24T00:00:00+00:00"]

    def boom(*_a, **_kw):
        raise RuntimeError("never costs the alerts pass")

    monkeypatch.setattr(triage, "maybe_start", boom)
    assert "note" in alerts.run_cycle(conn, settings, "2026-09-24T00:10:00+00:00")


def test_prune_keeps_sixty_days(site, tmp_path):
    settings, conn = site
    old = "2026-07-01T00:00:00+00:00"
    conn.execute("INSERT INTO triage_runs (id, started_at, status) VALUES (7, ?, 'ok')", (old,))
    conn.execute("INSERT INTO triage_actions (run_id, n, action) VALUES (7, 1, 'nudge_collector')")
    conn.execute("INSERT INTO triage_replies (message_id, received_at, verdict) VALUES ('<a>', ?, 'acted')", (old,))
    (tmp_path / "triage" / "7").mkdir(parents=True)
    conn.commit()
    assert triage.prune(conn, settings, "2026-09-24T00:00:00+00:00") == 1
    for table in ("triage_runs", "triage_actions", "triage_replies"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert not (tmp_path / "triage" / "7").exists()


# ---------------------------------------------------------------- settings

def test_the_new_settings_validate(site):
    settings, conn = site
    assert alerts._validate("alerts_triage_hours", " 18, 6 ,6") == "6,18"
    assert alerts._validate("alerts_triage_hours", "") == "6,18"
    for bad in ("24", "6,x", "1,2,3,4,5", "-1"):
        with pytest.raises(alerts.AlertError):
            alerts._validate("alerts_triage_hours", bad)
    assert alerts._validate("alerts_triage_reply_to", "a+ccsync@example.com") == "a+ccsync@example.com"
    for bad in ('a"@example.com', "a b@example.com", "a@example.com, b@example.com", "nope"):
        with pytest.raises(alerts.AlertError):
            alerts._validate("alerts_triage_reply_to", bad)
    with pytest.raises(alerts.AlertError):
        alerts._validate("alerts_imap_host", "imap.example.com; x")
    fresh = dbmod.connect(":memory:")
    dbmod.migrate(fresh)
    defaults = alerts.get_settings(fresh)
    assert defaults["alerts_triage"] == "0" and defaults["alerts_triage_hours"] == "6,18"


def test_imap_host_is_derived_from_smtp():
    assert triage_mail.imap_host({"alerts_smtp_host": "smtp.gmail.com"}) == "imap.gmail.com"
    assert triage_mail.imap_host({"alerts_smtp_host": "smtp.fastmail.com"}) == "imap.fastmail.com"
    assert triage_mail.imap_host({"alerts_smtp_host": "mail.example.com"}) == ""
    assert triage_mail.imap_host({"alerts_smtp_host": "smtp.gmail.com",
                                  "alerts_imap_host": "imap.other"}) == "imap.other"


class _FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        _FakeSMTP.sent.append(message)


def test_reply_to_reaches_the_smtp_header(site, monkeypatch):
    settings, conn = site
    _FakeSMTP.sent = []
    monkeypatch.setattr(alerts, "_smtp_class", lambda: _FakeSMTP)
    out = alerts._transmit(conn, settings, "s", "t", label="triage",
                           reply_to="owner+ccsync@example.com")
    assert out["ok"]
    assert _FakeSMTP.sent[0]["Reply-To"] == "owner+ccsync@example.com"
    alerts._transmit(conn, settings, "s", "t", label="test")
    assert _FakeSMTP.sent[1]["Reply-To"] is None


# ---------------------------------------------------------------- the page

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "_start_thread", lambda *a, **kw: None)
    app = create_app(Settings(db_path=str(tmp_path / "dash.db"), report_token="sekrit",
                              session_secret=SECRET, admin_users=frozenset({"owen"})))
    with TestClient(app) as c:
        c.app.state.collector.stop()
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield c
    if triage._RUN_LOCK.locked():
        triage._RUN_LOCK.release()


def test_the_alerts_page_has_the_server_check_block(client):
    page = client.get("/admin/alerts")
    assert page.status_code == 200
    # The terminal look (2026-09-25): a foldable "server check" window whose
    # Run now key submits the triage run form.
    assert 'aria-label="Fold server check"' in page.text
    assert '<span class="t">Run now</span>' in page.text
    assert 'form="alerts-run-form"' in page.text
    assert 'hx-post="/partials/admin/alerts/triage/run"' in page.text
    assert 'name="alerts_triage_reply_to"' in page.text
    assert EM not in page.text


def test_run_now_says_why_it_did_not_start_and_starts_when_on(client):
    answer = client.post("/partials/admin/alerts/triage/run")
    assert "the server check did not start" in answer.text
    saved = client.post("/partials/admin/alerts/save", data={
        "alerts_sink": "webhook", "alerts_webhook_url": "https://hooks.example/x",
        "alerts_triage": "1", "alerts_triage_hours": "6,18"})
    assert "Saved." in saved.text
    answer = client.post("/partials/admin/alerts/triage/run")
    assert "Server check started" in answer.text


def test_the_report_link_shows_what_was_mailed(client, tmp_path):
    conn = dbmod.connect(tmp_path / "dash.db")
    conn.execute("INSERT INTO triage_runs (id, started_at, status, report_json) "
                 "VALUES (3, '2026-09-24T00:00:00+00:00', 'ok', ?)",
                 (json.dumps({"subject": "[CC Sync] Server check: x", "body": "hello\n"}),))
    conn.commit()
    conn.close()
    assert client.get("/admin/alerts/triage/3").text == "Subject: [CC Sync] Server check: x\n\nhello\n"
    assert client.get("/admin/alerts/triage/4").status_code == 404


def test_every_catalogue_action_renders_in_the_prompt():
    prompt = triage.render_prompt("/pkg")
    for name in triage_actions.CATALOGUE:
        assert f"- {name}(" in prompt
    assert "approve_device" not in prompt
    assert "{catalogue}" not in prompt and "{package_dir}" not in prompt
