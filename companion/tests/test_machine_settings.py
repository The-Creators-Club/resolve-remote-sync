"""Fleet-jobs settings asked for from the dashboard's account page.

Account page 2026-09-25 (docs/ACCOUNT_PAGE_FEATURES.md sections 4 and 5, group
E). The dashboard keeps `commands.machine_settings` standing on every reply
until this computer answers, so applying must be idempotent; `mode` is never
requestable (CR-88); `jobs_kinds = ""` means EVERY kind, so an all-unknown list
is refused rather than written; nothing secret about YouTube leaves the machine.

Nothing here touches a real dashboard, tray or Tk window (conftest isolates
~/.ccsync and CONFIG_PATH).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from ccsync_companion import capabilities as capabilities_mod
from ccsync_companion import config as config_mod
from ccsync_companion import machine_settings as ms
from ccsync_companion.reporter import DashboardReporter

EM_DASH = "\u2014"
NOW = 1_790_000_000.0

CONFIG_TEXT = (
    "# a comment the owner wrote\n"
    'editor_name = "owen"\n'
    "jobs_enabled = true\n"
    "# jobs_kinds = \"whisper\"\n"
    "jobs_volunteer_minutes = 30\n"
    "\n"
    "[proxy]\n"
    'note = "a table the write must not land in"\n'
)


@pytest.fixture(autouse=True)
def _fresh_caches():
    ms._forget_disk_cache()
    ms._forget_memory()
    ms._kinds_cache.clear()
    yield
    ms._forget_disk_cache()
    ms._forget_memory()
    ms._kinds_cache.clear()


@pytest.fixture
def paths(tmp_path):
    config_path = config_mod.CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(CONFIG_TEXT, encoding="utf-8")
    ledger = tmp_path / "state" / ms.LEDGER_NAME
    return config_path, ledger


def _cmd(request_id="9f3c0a1b2c3d4e5f", by="tchen", **settings) -> dict[str, Any]:
    return {"id": request_id, "set": settings, "requested_by": by,
            "requested_at": "2026-09-25T10:00:00Z"}


def _apply(paths, command, now=NOW):
    config_path, ledger = paths
    return ms.apply_request(command, config_path=config_path, ledger_path=ledger, now=now)


def _on_disk(config_path: Path) -> dict[str, Any]:
    return config_mod.load_config(config_path)


# -- apply_request --------------------------------------------------------------


def test_applied_rewrites_one_line_and_reads_back(paths):
    config_path, ledger = paths
    before = config_path.read_text(encoding="utf-8").splitlines()

    answer = _apply(paths, _cmd(jobs_enabled=False))

    assert answer["state"] == "applied"
    assert answer["id"] == "9f3c0a1b2c3d4e5f"
    assert answer["detail"] == ""
    assert answer["at"].endswith("Z")
    after = config_path.read_text(encoding="utf-8").splitlines()
    assert _on_disk(config_path)["jobs_enabled"] is False
    # Every other line passes through byte for byte.
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert changed == [("jobs_enabled = true", "jobs_enabled = false")]
    assert len(before) == len(after)
    # The ledger holds the answer.
    assert ms.last_answer(ledger) == answer


def test_kinds_written_in_the_settings_windows_encoding(paths):
    config_path, _ = paths
    answer = _apply(paths, _cmd(jobs_kinds=["peaks", "proxy-480p", "peaks", "nonsense"]))
    assert answer["state"] == "applied"
    # Known-kinds order, duplicates dropped, unknown names filtered out.
    expected = ", ".join(k for k in capabilities_mod.KNOWN_KINDS
                         if k in ("peaks", "proxy-480p"))
    assert _on_disk(config_path)["jobs_kinds"] == expected
    assert capabilities_mod.job_kinds(_on_disk(config_path)) == expected.split(", ")


def test_every_kind_is_written_as_empty(paths):
    config_path, _ = paths
    answer = _apply(paths, _cmd(jobs_kinds=list(reversed(capabilities_mod.KNOWN_KINDS))))
    assert answer["state"] == "applied"
    assert _on_disk(config_path)["jobs_kinds"] == ""


def test_an_empty_kinds_list_is_every_kind(paths):
    config_path, _ = paths
    assert _apply(paths, _cmd(jobs_kinds=[]))["state"] == "applied"
    assert _on_disk(config_path)["jobs_kinds"] == ""


def test_all_unknown_kinds_are_refused_not_widened_to_every_kind(paths):
    config_path, _ = paths
    before = config_path.read_bytes()
    answer = _apply(paths, _cmd(jobs_kinds=["conform", "resolve-edit"]))
    assert answer["state"] == "refused"
    assert answer["detail"] == "this computer does not know those kinds of work"
    assert config_path.read_bytes() == before


@pytest.mark.parametrize("settings, detail", [
    ({"mode": "base"}, "this computer does not take mode from the dashboard"),
    ({"jobs_enabled": True, "mode": "editor"},
     "this computer does not take mode from the dashboard"),
    ({"jobs_volunteer_minutes": 60},
     "this computer does not take jobs_volunteer_minutes from the dashboard"),
    ({"jobs_enabled": "false"}, "jobs_enabled must be true or false"),
    ({"jobs_enabled": 0}, "jobs_enabled must be true or false"),
    ({"jobs_kinds": "whisper"}, None),
    ({"jobs_kinds": ["whisper", 3]}, None),
])
def test_refusals_write_nothing(paths, settings, detail):
    config_path, _ = paths
    before = config_path.read_bytes()
    answer = _apply(paths, _cmd(**settings))
    assert answer["state"] == "refused"
    if detail is not None:
        assert answer["detail"] == detail
    assert answer["detail"]
    assert EM_DASH not in answer["detail"]
    # Refused WHOLE: the valid half of a mixed request is not applied either.
    assert config_path.read_bytes() == before


@pytest.mark.parametrize("command", [
    None, "x", {}, {"id": "", "set": {}}, {"id": 5, "set": {"jobs_enabled": True}},
    {"id": "x" * 65, "set": {"jobs_enabled": True}}, {"id": "abc", "set": []},
    {"id": "abc"},
])
def test_malformed_commands_are_answered_with_nothing(paths, command):
    config_path, ledger = paths
    before = config_path.read_bytes()
    assert _apply(paths, command) == {}
    assert config_path.read_bytes() == before
    assert not ledger.exists()


def test_a_redelivered_id_is_answered_from_the_ledger(paths):
    config_path, _ = paths
    first = _apply(paths, _cmd(jobs_enabled=False))
    # Someone flips it back at the tray; the standing command arrives again.
    config_mod.set_value(config_path, "jobs_enabled", True)
    before = config_path.read_bytes()
    again = _apply(paths, _cmd(jobs_enabled=False), now=NOW + 30)
    assert again == first
    assert config_path.read_bytes() == before, "a redelivery rewrote config.toml"


def test_a_refusal_is_redelivered_from_the_ledger_too(paths):
    first = _apply(paths, _cmd(mode="base"))
    assert _apply(paths, _cmd(mode="base"), now=NOW + 30) == first


def test_a_new_id_applies_again(paths):
    config_path, _ = paths
    _apply(paths, _cmd(request_id="a" * 16, jobs_enabled=False))
    answer = _apply(paths, _cmd(request_id="b" * 16, jobs_enabled=True))
    assert answer["state"] == "applied" and answer["id"] == "b" * 16
    assert _on_disk(config_path)["jobs_enabled"] is True


def test_a_failed_write_is_retried_only_after_the_floor(paths, monkeypatch):
    config_path, _ = paths
    calls = []

    def refusing(path, key, value):
        calls.append((key, value))
        return False

    monkeypatch.setattr(config_mod, "set_value", refusing)
    first = _apply(paths, _cmd(jobs_enabled=False))
    assert first["state"] == "failed"
    assert first["detail"] == "could not save config.toml"
    assert len(calls) == 1

    # Inside the floor: the recorded answer, no second write.
    again = _apply(paths, _cmd(jobs_enabled=False), now=NOW + ms.FAILED_RETRY_SECONDS - 1)
    assert again == first
    assert len(calls) == 1

    # After the floor, a write that works: applied.
    monkeypatch.undo()
    later = _apply(paths, _cmd(jobs_enabled=False), now=NOW + ms.FAILED_RETRY_SECONDS + 1)
    assert later["state"] == "applied"
    assert _on_disk(config_path)["jobs_enabled"] is False


def test_a_raising_write_is_failed_not_raised(paths, monkeypatch):
    def boom(path, key, value):
        raise OSError("disk full")

    monkeypatch.setattr(config_mod, "set_value", boom)
    assert _apply(paths, _cmd(jobs_enabled=False))["state"] == "failed"


def test_an_unreadable_ledger_is_treated_as_empty(paths):
    _, ledger = paths
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{not json", encoding="utf-8")
    assert _apply(paths, _cmd(jobs_enabled=False))["state"] == "applied"
    assert ms.last_answer(ledger)["state"] == "applied"


def test_the_ledger_keeps_a_bounded_history(paths):
    _, ledger = paths
    for i in range(ms._LEDGER_KEEP + 5):
        _apply(paths, _cmd(request_id=f"id{i:04d}", jobs_enabled=bool(i % 2)))
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(data["answers"]) == ms._LEDGER_KEEP
    assert data["last"]["id"] == f"id{ms._LEDGER_KEEP + 4:04d}"


# -- report_section ------------------------------------------------------------


class _App:
    def __init__(self, config, state_dir):
        self.config = config
        self._state_dir = state_dir

    def editor_identity(self):
        return "owen"


def test_section_shape_and_running_values(paths, tmp_path):
    app = _App({"jobs_enabled": True, "jobs_volunteer_minutes": 45,
                "drive_reminder_minutes": 0}, tmp_path / "state")
    section = ms.report_section(app)
    assert section["accepts"] == ["jobs_enabled", "jobs_kinds"]
    assert section["jobs_volunteer_minutes"] == 45
    assert section["drive_reminder_minutes"] == 0.0
    assert "applied" not in section
    json.dumps(section)


@pytest.mark.parametrize("raw, minutes", [(-5, 30), ("abc", 30), (0, 30), (None, 30)])
def test_lend_length_uses_the_windows_coercion(paths, tmp_path, raw, minutes):
    app = _App({"jobs_volunteer_minutes": raw}, tmp_path / "state")
    assert ms.report_section(app)["jobs_volunteer_minutes"] == minutes


@pytest.mark.parametrize("raw", [-1, "soon", True, float("nan")])
def test_drive_reminder_falls_back_to_the_default(paths, tmp_path, raw):
    app = _App({"drive_reminder_minutes": raw}, tmp_path / "state")
    assert ms.report_section(app)["drive_reminder_minutes"] == \
        float(config_mod.DEFAULTS["drive_reminder_minutes"])


def test_pending_restart_names_only_differing_keys_with_disk_values(paths, tmp_path):
    config_path, _ = paths
    running = dict(_on_disk(config_path))
    app = _App(running, tmp_path / "state")
    assert ms.report_section(app)["pending_restart"] == {}

    config_mod.set_value(config_path, "jobs_enabled", False)
    config_mod.set_value(config_path, "jobs_kinds", "peaks")
    section = ms.report_section(app)
    assert section["pending_restart"] == {"jobs_enabled": False, "jobs_kinds": ["peaks"]}


def test_pending_restart_compares_kinds_as_lists(paths, tmp_path):
    config_path, _ = paths
    # A hand-edited " peaks " and a running ["peaks"] are the same kinds
    # (capabilities.job_kinds cleans both) and must not read as a change.
    config_mod.set_value(config_path, "jobs_kinds", " peaks ")
    running = dict(_on_disk(config_path))
    running["jobs_kinds"] = ["peaks"]
    assert ms.report_section(_App(running, tmp_path / "state"))["pending_restart"] == {}


def test_config_is_reread_only_when_it_changes(paths, tmp_path, monkeypatch):
    config_path, _ = paths
    app = _App(dict(_on_disk(config_path)), tmp_path / "state")
    reads = []
    real = config_mod.load_config
    monkeypatch.setattr(config_mod, "load_config",
                        lambda path=config_mod.CONFIG_PATH: reads.append(path) or real(path))
    ms.report_section(app)
    ms.report_section(app)
    assert len(reads) == 1
    # A write through set_value changes the file; the next section sees it.
    time.sleep(0.01)
    config_mod.set_value(config_path, "jobs_enabled", False)
    reads.clear()                    # set_value reads the file back itself
    # No cache reset here (review round): the mtime + size change alone must
    # make the next section read the file again, once.
    assert ms.report_section(app)["pending_restart"] == {"jobs_enabled": False}
    assert len(reads) == 1
    ms.report_section(app)
    assert len(reads) == 1


def test_youtube_is_omitted_when_the_site_has_it_off(paths, tmp_path, monkeypatch):
    from ccsync_companion import site as site_mod

    monkeypatch.setattr(site_mod, "feature_enabled", lambda name, site=None: False)
    section = ms.report_section(_App({}, tmp_path / "state"))
    assert "youtube" not in section
    assert section["accepts"]


def test_youtube_status_words_only_no_cookie_no_reason(paths, tmp_path, monkeypatch):
    from ccsync_companion import tray as tray_mod
    from ccsync_companion import ytdl_cookies

    secret_reason = "Sign in to confirm you are not a bot SECRET-REASON-TEXT"
    monkeypatch.setattr(ytdl_cookies, "health", lambda cfg=None, path=None, now=None: {
        "status": "stale", "reason": secret_reason, "at": "2026-09-25T00:00:00Z",
        "cookies": "SID=SECRET-COOKIE"})
    monkeypatch.setattr(tray_mod, "_ytdl_attested", lambda app: True)
    cfg = {"ytdl_cookies_path": str(tmp_path / "cookies-SECRET-PATH.txt")}
    section = ms.report_section(_App(cfg, tmp_path / "state"))
    assert section["youtube"] == {"downloads": True, "signin_enabled": True,
                                  "terms_accepted": True, "signin": "stale"}
    text = json.dumps(section)
    for secret in ("SECRET-REASON-TEXT", "SECRET-COOKIE", "SECRET-PATH"):
        assert secret not in text


def test_youtube_opted_out_machine_reports_downloads_false(paths, tmp_path):
    section = ms.report_section(_App({"ytdl_local_downloads": False}, tmp_path / "state"))
    assert section["youtube"]["downloads"] is False
    assert section["youtube"]["signin_enabled"] is False
    assert section["youtube"]["signin"] == "none"


def test_section_carries_the_ledgers_last_answer(paths, tmp_path):
    _apply(paths, _cmd(mode="base"))
    app = _App({}, paths[1].parent)
    applied = ms.report_section(app)["applied"]
    assert applied["id"] == "9f3c0a1b2c3d4e5f"
    assert applied["state"] == "refused"
    assert set(applied) == {"id", "state", "detail", "at"}


def test_section_never_raises(tmp_path, monkeypatch):
    class Broken:
        @property
        def config(self):
            raise RuntimeError("boom")

    assert ms.report_section(Broken()) == {}


# -- change_sentence -------------------------------------------------------------


def test_balloon_sentences():
    assert ms.change_sentence({"jobs_enabled": False}, "tchen") == (
        "tchen asked this computer to stop taking fleet work. It takes effect "
        "the next time CCSync starts.")
    text = ms.change_sentence({"jobs_kinds": ["proxy-480p", "peaks"]}, "owen")
    assert text.startswith("owen asked this computer to take only these kinds of "
                           "fleet work: Make small preview copies of video, "
                           "Draw audio waveforms.")
    assert "every kind" in ms.change_sentence({"jobs_kinds": []}, "owen")
    assert ms.change_sentence({}, "").startswith("Your administrator")
    for s in (text, ms.change_sentence({"jobs_enabled": True, "jobs_kinds": ["x"]}, "a")):
        assert EM_DASH not in s


# -- reporter ------------------------------------------------------------------


def _reporter(getter, posts):
    def fake_post(url, data, headers, timeout):
        posts.append(json.loads(data) if isinstance(data, (bytes, str)) else data)
        return {}

    cfg = {"editor_name": "owen", "dashboard_url": "http://dash.example.com",
           "dashboard_token": "tok123", "dashboard_report_interval": 60}
    return DashboardReporter(lambda: [], cfg, http_post=fake_post,
                             get_machine_settings=getter)


def test_the_section_rides_light_and_heavy_ticks():
    section = {"accepts": ["jobs_enabled", "jobs_kinds"], "pending_restart": {}}
    posts: list = []
    reporter = _reporter(lambda: section, posts)
    assert reporter._build_payload(light=True)["machine_settings"] == section
    assert reporter._build_payload(light=False)["machine_settings"] == section
    reporter.post_once(light=True)
    assert posts and posts[-1]["machine_settings"] == section


def test_a_raising_getter_omits_the_section_and_the_report_still_posts():
    posts: list = []

    def boom():
        raise RuntimeError("boom")

    reporter = _reporter(boom, posts)
    reporter.post_once()
    assert len(posts) == 1
    assert "machine_settings" not in posts[0]


def test_an_empty_section_is_omitted():
    posts: list = []
    reporter = _reporter(lambda: {}, posts)
    assert "machine_settings" not in reporter._build_payload(light=True)


def test_no_getter_no_section():
    posts: list = []
    reporter = _reporter(None, posts)
    assert "machine_settings" not in reporter._build_payload(light=True)


# -- app wiring ------------------------------------------------------------------


def _app(tmp_path):
    from ccsync_companion.app import CompanionApp

    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    app = CompanionApp(cfg)
    balloons: list = []
    app._notify_tray = lambda msg, title="": balloons.append((msg, title))
    return app, balloons


def _join_off_cycle_reports() -> None:
    for thread in list(threading.enumerate()):
        if thread.name == "ccsync-report-off-cycle":
            thread.join(timeout=5)


@pytest.mark.parametrize("resp", [
    None, "garbage", 5, [], {}, {"commands": None}, {"commands": []},
    {"commands": {"machine_settings": None}},
    {"commands": {"machine_settings": "x"}},
    {"commands": {"machine_settings": {"id": None, "set": None}}},
    {"commands": {"machine_settings": {"id": "abc", "set": "x"}}},
    {"commands": {"machine_settings": {"id": ["x"], "set": {"jobs_enabled": 1}}}},
])
def test_app_never_raises_on_garbage(tmp_path, resp):
    app, balloons = _app(tmp_path)
    app._apply_machine_settings_request(resp)
    assert balloons == []
    _join_off_cycle_reports()


def test_app_balloons_once_per_new_id(tmp_path):
    app, balloons = _app(tmp_path)
    reply = {"ok": True, "commands": {"machine_settings": _cmd(jobs_enabled=False)}}

    app._apply_machine_settings_request(reply)
    assert len(balloons) == 1
    msg, title = balloons[0]
    assert msg.startswith("tchen asked this computer to stop taking fleet work.")
    assert "fleet work settings changed" in title
    assert config_mod.load_config(config_mod.CONFIG_PATH)["jobs_enabled"] is False
    ledger = Path(app._state_dir) / ms.LEDGER_NAME
    assert ms.last_answer(ledger)["state"] == "applied"

    # The standing command, redelivered on the next replies: no new balloon.
    app._apply_machine_settings_request(reply)
    app._apply_machine_settings_request(reply)
    assert len(balloons) == 1

    # A new ask is a new balloon.
    app._apply_machine_settings_request(
        {"commands": {"machine_settings": _cmd(request_id="c" * 16, jobs_enabled=True)}})
    assert len(balloons) == 2
    # And the report section now carries that answer.
    assert ms.report_section(app)["applied"]["id"] == "c" * 16
    _join_off_cycle_reports()


def test_app_does_not_balloon_a_refusal(tmp_path):
    app, balloons = _app(tmp_path)
    app._apply_machine_settings_request(
        {"commands": {"machine_settings": _cmd(mode="base")}})
    assert balloons == []
    ledger = Path(app._state_dir) / ms.LEDGER_NAME
    assert ms.last_answer(ledger)["state"] == "refused"
    _join_off_cycle_reports()


def test_app_report_section_is_wired(tmp_path):
    app, _ = _app(tmp_path)
    reporter = getattr(app, "reporter", None) or getattr(app, "_reporter", None)
    if reporter is None:
        pytest.skip("no reporter without a dashboard_url")
    assert reporter._get_machine_settings is not None
    _join_off_cycle_reports()


# -- review round (account page 2026-09-25) ------------------------------------


def _break_config(config_path: Path, *, keep_backup: bool) -> None:
    config_mod.load_config(config_path)          # refreshes config.toml.bak
    if not keep_backup:
        config_mod.backup_path(config_path).unlink(missing_ok=True)
    config_path.write_text("jobs_enabled = [unterminated\n", encoding="utf-8")


def test_a_broken_config_with_no_backup_leaves_pending_restart_out(paths, tmp_path):
    config_path, _ = paths
    # The reviewer's case: running jobs off + peaks only, config.toml broken.
    # load_config returns ALL DEFAULTS then, and those must not be reported
    # as a saved change ("take every kind, enabled") waiting for a restart.
    running = {"jobs_enabled": False, "jobs_kinds": "peaks"}
    _break_config(config_path, keep_backup=False)
    section = ms.report_section(_App(running, tmp_path / "state"))
    assert "pending_restart" not in section
    assert section["accepts"] == ["jobs_enabled", "jobs_kinds"]


def test_a_broken_config_is_asked_again_every_tick(paths, tmp_path):
    config_path, _ = paths
    running = dict(_on_disk(config_path))
    running["jobs_enabled"] = True
    _break_config(config_path, keep_backup=False)
    app = _App(running, tmp_path / "state")
    assert "pending_restart" not in ms.report_section(app)
    config_path.write_text(CONFIG_TEXT.replace("jobs_enabled = true", "jobs_enabled = false"),
                           encoding="utf-8")
    assert ms.report_section(app)["pending_restart"] == {"jobs_enabled": False}


def test_a_broken_config_rescued_from_the_backup_is_still_compared(paths, tmp_path):
    config_path, _ = paths
    config_mod.set_value(config_path, "jobs_enabled", False)
    _break_config(config_path, keep_backup=True)
    running = {"jobs_enabled": True}
    section = ms.report_section(_App(running, tmp_path / "state"))
    assert section["pending_restart"] == {"jobs_enabled": False}


def test_a_raising_config_read_leaves_pending_restart_out(paths, tmp_path, monkeypatch):
    def boom(path=None):
        raise OSError("gone")

    monkeypatch.setattr(config_mod, "load_config", boom)
    section = ms.report_section(_App({"jobs_enabled": True}, tmp_path / "state"))
    assert "pending_restart" not in section
    assert section["accepts"] == ["jobs_enabled", "jobs_kinds"]


def test_kinds_in_a_different_order_are_not_a_pending_change(paths, tmp_path):
    config_path, _ = paths
    config_mod.set_value(config_path, "jobs_kinds", "whisper, peaks")
    running = dict(_on_disk(config_path))
    running["jobs_kinds"] = "peaks, whisper"
    assert ms.report_section(_App(running, tmp_path / "state"))["pending_restart"] == {}
    # A different SET still is, with the on-disk list as the reported value.
    running["jobs_kinds"] = "peaks"
    pending = ms.report_section(_App(running, tmp_path / "state"))["pending_restart"]
    assert set(pending["jobs_kinds"]) == {"whisper", "peaks"}


def test_an_unwritable_ledger_still_answers_redeliveries_from_memory(paths, monkeypatch):
    config_path, ledger = paths
    writes = []
    real_set = config_mod.set_value
    monkeypatch.setattr(config_mod, "set_value",
                        lambda p, k, v: writes.append((k, v)) or real_set(p, k, v))
    monkeypatch.setattr(ms, "_write_ledger", lambda path, data: False)

    first = _apply(paths, _cmd(jobs_enabled=False))
    assert first["state"] == "applied"
    assert not ledger.exists()
    assert len(writes) == 1

    # The standing command, redelivered: answered, not applied again.
    assert _apply(paths, _cmd(jobs_enabled=False), now=NOW + 30) == first
    assert _apply(paths, _cmd(jobs_enabled=False), now=NOW + 60) == first
    assert len(writes) == 1
    # And the report carries the answer, so the dashboard stops sending it.
    assert ms.last_answer(ledger)["id"] == first["id"]
    assert ms.answer_for(ledger, first["id"]) == first


def test_memory_and_file_agree_after_a_restart(paths):
    _, ledger = paths
    first = _apply(paths, _cmd(jobs_enabled=False))
    ms._forget_memory()                          # CCSync restarted
    assert ms.last_answer(ledger) == first
    assert ms.answer_for(ledger, first["id"]) == first


def test_app_unwritable_ledger_balloons_once(tmp_path, monkeypatch):
    app, balloons = _app(tmp_path)
    monkeypatch.setattr(ms, "_write_ledger", lambda path, data: False)
    reply = {"ok": True, "commands": {"machine_settings": _cmd(jobs_enabled=False)}}
    for _ in range(4):
        app._apply_machine_settings_request(reply)
    assert len(balloons) == 1
    assert ms.report_section(app)["applied"]["state"] == "applied"
    _join_off_cycle_reports()


def test_the_report_reply_fan_out_applies_the_request(tmp_path):
    # The one production call site is inside _on_report_response_locked;
    # drive it through the public fan-out so removing that line fails here.
    app, balloons = _app(tmp_path)
    reply = {"ok": True, "commands": {"machine_settings": _cmd(jobs_enabled=False)}}
    app._on_report_response(reply)
    assert config_mod.load_config(config_mod.CONFIG_PATH)["jobs_enabled"] is False
    assert ms.last_answer(Path(app._state_dir) / ms.LEDGER_NAME)["state"] == "applied"
    assert len(balloons) == 1
    app._on_report_response(reply)
    assert len(balloons) == 1
    _join_off_cycle_reports()
