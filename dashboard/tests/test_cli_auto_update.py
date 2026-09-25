"""CR-309 (2026-09-24): the dashboard keeps its Claude Code CLI current.

Timeline Cards passes the CLI a family alias (`opus`), and an alias is only
as new as the CLI resolving it: on 2026-09-23 the installed 2.1.267 refused
`claude-opus-5-5` until it was updated by hand. `cli_tools.auto_update_tick`
is the admin's UPDATE button pressed by the collector at most once a day.

What this file holds down:

* **The same verified path, or nothing.** An update goes through
  `start_install` -> `_install_claude`, so the publisher's manifest checksum
  is a CONDITION: a release without one is refused and nothing moves.
* **Never a downgrade**, and never a second install beside a running one.
* **Off means off**: the site feature, the CLI feature and a wizard install
  are all required, and a look is not spent while any is missing.
* **A failure is a notice, never an exception** in the collector.
* **At most once per interval**, with the first look after boot delayed.
* **The replaced version outlives the flip** by PRUNE_GRACE_SECONDS, so a
  call already running it keeps its file.

No socket, no binary, no real clock: `latest_claude_version`, `_fetch_json`,
`release_feed.open_https_stream` and `platform_key` are the seams.
"""
from __future__ import annotations

import hashlib
import json
import time

import pytest

from ccsync_dashboard import ai_providers, cli_tools, notices
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.settings import Settings

NAME = cli_tools.CLAUDE_CODE
DAY = cli_tools.AUTO_UPDATE_INTERVAL
PAYLOAD = b"pretend this is 313 MiB of claude 2.1.280"


@pytest.fixture(autouse=True)
def _cold_module_state(monkeypatch):
    """The updater's latches are process globals; start every test from a
    process that booted long ago and has never looked."""
    cli_tools._install_status.clear()
    cli_tools._install_running = ""
    monkeypatch.setattr(cli_tools, "_auto_running", False)
    monkeypatch.setattr(cli_tools, "_auto_checked_this_process", False)
    monkeypatch.setattr(cli_tools, "_auto_last_checked", 0.0)
    monkeypatch.setattr(cli_tools, "_auto_process_started", 0.0)
    monkeypatch.setattr(cli_tools, "_auto_last_sweep", 0.0)
    monkeypatch.setattr(cli_tools, "_auto_reconsider_at", 0.0)
    ai_providers.reset_probe_cache()
    yield
    cli_tools._install_status.clear()
    cli_tools._install_running = ""


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return Settings(db_path=str(tmp_path / "d.db"), session_secret="test-secret",
                    admin_users=frozenset({"owen"}))


@pytest.fixture
def conn(settings):
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    yield c
    c.close()


def set_feature(conn, name, on=True):
    conn.execute(
        "INSERT INTO site_settings (key, value, updated_at, updated_by) "
        "VALUES (?, ?, 'now', 'test') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"features.{name}", "1" if on else "0"))
    conn.commit()


def enable(conn):
    set_feature(conn, "ai_cli_providers")
    set_feature(conn, cli_tools.AUTO_UPDATE_FEATURE)


def install_version(settings, version="2.1.267"):
    """A wizard install of `version`, as `_finish_install` leaves it."""
    d = cli_tools.tool_root(settings, NAME) / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "claude").write_bytes(b"old claude")
    cli_tools._finish_install(settings, NAME, version=version, rel="claude",
                              sha="a" * 64, size=10, url="https://x/claude",
                              checksum_source="publisher_manifest")


class FakeResponse:
    def __init__(self, data: bytes):
        self._data = data
        self._at = 0

    def read(self, size=-1):
        out = self._data[self._at:self._at + (size if size and size > 0 else len(self._data))]
        self._at += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def publisher(monkeypatch, latest="2.1.280", checksum="auto", data=PAYLOAD):
    """The publisher: `latest`, a manifest, and the binary's bytes. Returns
    the list of URLs actually fetched."""
    fetched: list[str] = []
    monkeypatch.setattr(cli_tools, "platform_key", lambda *a, **k: "linux-x64")
    monkeypatch.setattr(cli_tools, "install_supported", lambda s, n="": (True, ""))

    def latest_fn(fetch=None):
        fetched.append("latest")
        return cli_tools.validate_version(latest)

    entry = {"binary": "claude", "size": len(data)}
    if checksum == "auto":
        entry["checksum"] = hashlib.sha256(data).hexdigest()
    elif checksum:
        entry["checksum"] = checksum

    def fetch_json(url):
        fetched.append(url)
        return {"version": latest, "platforms": {"linux-x64": entry}}

    def opener(url, *, timeout):
        fetched.append(url)
        return FakeResponse(data)

    monkeypatch.setattr(cli_tools, "latest_claude_version", latest_fn)
    monkeypatch.setattr(cli_tools, "_fetch_json", fetch_json)
    monkeypatch.setattr(cli_tools.release_feed, "open_https_stream", opener)
    return fetched


def run_now(fn):
    """`spawn` for the tests: the look runs on this thread."""
    fn()


def wait_for_result(settings, *results, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = cli_tools.read_auto_update(settings)
        if record.get("result") in results and not cli_tools._install_running:
            return record
        time.sleep(0.02)
    raise AssertionError(f"no {results} outcome: {cli_tools.read_auto_update(settings)}")


NOW = 10 * DAY


# ------------------------------------------------------------ the happy path

def test_a_newer_release_is_installed_through_the_verified_path(settings, conn,
                                                                monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    fetched = publisher(monkeypatch, latest="2.1.280")
    reset = []
    monkeypatch.setattr(cli_tools, "_reset_probe_cache", lambda: reset.append(1))

    assert cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now) == "started"
    record = wait_for_result(settings, "updated")

    assert record["installed"] == "2.1.280" and record["previous"] == "2.1.267"
    binary = cli_tools.installed_binary(settings, NAME)
    assert binary.endswith("2.1.280/claude") or binary.endswith("2.1.280\\claude")
    state = cli_tools.read_state(settings, NAME)
    # the checksum came from the publisher's manifest, exactly as the button's
    assert state["checksum_source"] == "publisher_manifest"
    assert state["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert any(u.endswith("/2.1.280/manifest.json") for u in fetched)
    # the Settings page's cached "which version" answer is dropped
    assert reset
    # ...and it shows as the wizard's own install, marked as ours
    assert cli_tools._install_status[NAME]["started_by"] == "auto-update"


def test_the_same_version_does_nothing(settings, conn, monkeypatch):
    enable(conn)
    install_version(settings, "2.1.280")
    fetched = publisher(monkeypatch, latest="2.1.280")
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    record = cli_tools.read_auto_update(settings)
    assert record["result"] == "up_to_date"
    assert fetched == ["latest"]                       # no manifest, no download
    assert cli_tools.read_state(settings, NAME)["installed_version"] == "2.1.280"


def test_an_older_release_is_never_installed(settings, conn, monkeypatch):
    enable(conn)
    install_version(settings, "2.1.280")
    fetched = publisher(monkeypatch, latest="2.1.99")    # 99 < 280 as numbers
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    assert cli_tools.read_auto_update(settings)["result"] == "up_to_date"
    assert fetched == ["latest"]
    assert cli_tools.read_state(settings, NAME)["installed_version"] == "2.1.280"


def test_latest_moving_backwards_between_the_look_and_the_install_is_refused(
        settings, conn, monkeypatch):
    """The worker asks the publisher again; a `latest` withdrawn in between
    is a refusal, not the older binary."""
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch, latest="2.1.280")
    answers = iter(["2.1.280", "2.1.260"])
    monkeypatch.setattr(cli_tools, "latest_claude_version",
                        lambda fetch=None: next(answers))
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    record = wait_for_result(settings, "failed")
    assert "not newer" in record["detail"]
    assert cli_tools.read_state(settings, NAME)["installed_version"] == "2.1.267"


# ------------------------------------------------------------ the refusals

def test_a_release_with_no_checksum_is_refused_and_nothing_moves(settings, conn,
                                                                 monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    fetched = publisher(monkeypatch, latest="2.1.280", checksum="")
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    record = wait_for_result(settings, "failed")
    assert "checksum" in record["detail"]
    # nothing downloaded, nothing flipped
    assert not any(u.endswith("/claude") and "2.1.280" in u for u in fetched)
    assert cli_tools.read_state(settings, NAME)["installed_version"] == "2.1.267"
    assert "2.1.267" in cli_tools.installed_binary(settings, NAME)


def test_a_download_that_does_not_match_the_checksum_is_refused(settings, conn,
                                                                monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch, latest="2.1.280", checksum="b" * 64)
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    record = wait_for_result(settings, "failed")
    assert "sha256" in record["detail"]
    assert cli_tools.read_state(settings, NAME)["installed_version"] == "2.1.267"


@pytest.mark.parametrize("which", ["ai_cli_providers", cli_tools.AUTO_UPDATE_FEATURE])
def test_either_feature_off_does_nothing_and_spends_no_look(settings, conn,
                                                            monkeypatch, which):
    enable(conn)
    set_feature(conn, which, on=False)
    install_version(settings, "2.1.267")
    fetched = publisher(monkeypatch)
    assert cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now) == "off"
    assert fetched == []
    assert "last_checked_epoch" not in cli_tools.read_auto_update(settings)
    # ...so turning it on is answered within a minute, not a day later
    set_feature(conn, which, on=True)
    later = NOW + cli_tools.AUTO_UPDATE_RECONSIDER
    assert cli_tools.auto_update_tick(conn, settings, now=later, spawn=run_now) == "started"


def test_the_vendor_default_is_off(settings, conn, monkeypatch):
    """No site row at all: the vendor build's shape."""
    install_version(settings, "2.1.267")
    fetched = publisher(monkeypatch)
    set_feature(conn, "ai_cli_providers")
    assert cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now) == "off"
    assert fetched == []


def test_a_cli_the_wizard_did_not_install_is_left_alone(settings, conn, monkeypatch):
    """A path the admin typed is theirs to update."""
    enable(conn)
    fetched = publisher(monkeypatch)
    assert (cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
            == "not installed")
    assert fetched == []


def test_a_manual_install_that_is_running_wins(settings, conn, monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch, latest="2.1.280")
    cli_tools._install_running = NAME                  # the admin clicked first
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    record = cli_tools.read_auto_update(settings)
    assert record["result"] == "skipped"
    assert "already running" in record["detail"]
    assert cli_tools._install_running == NAME          # not ours to release


def test_an_unrecorded_installed_version_is_never_guessed_at(settings, conn,
                                                            monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    cli_tools.state_path(settings, NAME).write_text("{not json", encoding="utf-8")
    fetched = publisher(monkeypatch)
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    assert cli_tools.read_auto_update(settings)["result"] == "skipped"
    assert fetched == []


# ------------------------------------------------------------ failures surface

def test_a_publisher_that_cannot_be_reached_is_recorded_not_raised(settings, conn,
                                                                    monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch)

    def down(fetch=None):
        raise cli_tools.ToolError("could not reach https://downloads.claude.ai (URLError)")

    monkeypatch.setattr(cli_tools, "latest_claude_version", down)
    assert cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now) == "started"
    record = cli_tools.read_auto_update(settings)
    assert record["result"] == "failed" and "could not reach" in record["detail"]
    assert cli_tools._auto_running is False


def test_an_unexpected_crash_is_recorded_not_raised(settings, conn, monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch)
    monkeypatch.setattr(cli_tools, "latest_claude_version",
                        lambda fetch=None: 1 / 0)
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    record = cli_tools.read_auto_update(settings)
    assert record["result"] == "failed" and "ZeroDivisionError" in record["detail"]
    assert cli_tools._auto_running is False


def test_a_tick_that_breaks_never_raises_into_the_collector(settings, conn,
                                                           monkeypatch):
    monkeypatch.setattr(cli_tools, "_auto_due",
                        lambda s, n: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now) == ""


def test_a_failure_is_a_notice_and_a_later_success_closes_it(settings, conn,
                                                            monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch, latest="2.1.280", checksum="")
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    wait_for_result(settings, "failed")

    notices._check_ai_cli_update(conn, settings, dbmod.utcnow_iso())
    conn.commit()
    rows = conn.execute("SELECT * FROM notices WHERE kind = ? AND cleared_at IS NULL",
                        (notices.AI_CLI_UPDATE_KIND,)).fetchall()
    assert len(rows) == 1
    body = rows[0]["body"]
    assert "2.1.267" in body and "2.1.280" in body and "checksum" in body
    assert "—" not in body and "—" not in (rows[0]["fix"] or "")
    assert notices.AI_CLI_UPDATE_KIND in dbmod.NOTICE_KINDS

    # the publisher fixes its manifest; the next day's look goes through
    publisher(monkeypatch, latest="2.1.280")
    cli_tools.auto_update_tick(conn, settings, now=NOW + DAY, spawn=run_now)
    wait_for_result(settings, "updated")
    notices._check_ai_cli_update(conn, settings, dbmod.utcnow_iso())
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM notices WHERE kind = ? AND "
                        "cleared_at IS NULL",
                        (notices.AI_CLI_UPDATE_KIND,)).fetchone()[0] == 0


def test_switching_the_feature_off_closes_a_failure_card(settings, conn,
                                                        monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch, checksum="")
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    wait_for_result(settings, "failed")
    notices._check_ai_cli_update(conn, settings, dbmod.utcnow_iso())
    set_feature(conn, cli_tools.AUTO_UPDATE_FEATURE, on=False)
    notices._check_ai_cli_update(conn, settings, dbmod.utcnow_iso())
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM notices WHERE kind = ? AND "
                        "cleared_at IS NULL",
                        (notices.AI_CLI_UPDATE_KIND,)).fetchone()[0] == 0


# ------------------------------------------------------------ the cadence

def test_never_more_than_once_per_interval(settings, conn, monkeypatch):
    enable(conn)
    install_version(settings, "2.1.280")
    fetched = publisher(monkeypatch, latest="2.1.280")
    looks = []
    for offset in (0, 60, 3600, DAY - 1, DAY, DAY + 60, 2 * DAY - 1, 2 * DAY):
        if cli_tools.auto_update_tick(conn, settings, now=NOW + offset,
                                      spawn=run_now) == "started":
            looks.append(offset)
    assert looks == [0, DAY, 2 * DAY]
    assert fetched.count("latest") == 3


def test_nothing_is_looked_at_in_the_first_minutes_after_boot(settings, conn,
                                                             monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    fetched = publisher(monkeypatch)
    monkeypatch.setattr(cli_tools, "_auto_process_started", NOW)
    assert cli_tools.auto_update_tick(conn, settings, now=NOW + 10, spawn=run_now) == ""
    assert fetched == []
    boot = NOW + cli_tools.AUTO_UPDATE_BOOT_DELAY
    assert cli_tools.auto_update_tick(conn, settings, now=boot, spawn=run_now) == "started"


def test_a_restart_loop_does_not_ask_the_publisher_every_lap(settings, conn,
                                                            monkeypatch):
    """The last look is on disk: a process started ten minutes after the last
    one looked waits for the boot floor, not the boot delay."""
    enable(conn)
    install_version(settings, "2.1.280")
    publisher(monkeypatch, latest="2.1.280")
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    # a new process: every in-memory latch is cold again
    monkeypatch.setattr(cli_tools, "_auto_checked_this_process", False)
    monkeypatch.setattr(cli_tools, "_auto_last_checked", 0.0)
    monkeypatch.setattr(cli_tools, "_auto_process_started", NOW + 60)
    soon = NOW + 60 + cli_tools.AUTO_UPDATE_BOOT_DELAY
    assert cli_tools.auto_update_tick(conn, settings, now=soon, spawn=run_now) == ""
    after_floor = NOW + cli_tools.AUTO_UPDATE_BOOT_FLOOR
    assert (cli_tools.auto_update_tick(conn, settings, now=after_floor, spawn=run_now)
            == "started")


def test_a_look_still_running_is_not_started_twice(settings, conn, monkeypatch):
    enable(conn)
    install_version(settings, "2.1.267")
    publisher(monkeypatch)
    held = []
    assert cli_tools.auto_update_tick(conn, settings, now=NOW,
                                      spawn=held.append) == "started"
    # the first look has not run yet (it is in `held`), and a clock that
    # jumped a day must not start a second one beside it
    assert cli_tools.auto_update_tick(conn, settings, now=NOW + DAY,
                                      spawn=held.append) == "running"
    assert len(held) == 1


# ------------------------------------------------------------ the replaced version

def test_the_replaced_version_outlives_the_flip_by_the_grace(settings):
    install_version(settings, "2.1.267")
    install_version(settings, "2.1.280")
    root = cli_tools.tool_root(settings, NAME)
    # a call started on 2.1.267 before the flip still has its file
    assert (root / "2.1.267" / "claude").is_file()
    state = cli_tools.read_state(settings, NAME)
    assert state["previous_version"] == "2.1.267"
    since = state["superseded_at_epoch"]

    assert cli_tools.sweep_superseded(settings, NAME,
                                      now=since + cli_tools.PRUNE_GRACE_SECONDS - 1) == ""
    assert (root / "2.1.267").is_dir()
    assert cli_tools.sweep_superseded(
        settings, NAME, now=since + cli_tools.PRUNE_GRACE_SECONDS) == "2.1.267"
    assert not (root / "2.1.267").exists()
    assert (root / "2.1.280" / "claude").is_file()
    assert "previous_version" not in cli_tools.read_state(settings, NAME)


def test_a_third_install_prunes_everything_but_the_live_and_the_last(settings,
                                                                    monkeypatch):
    # Changed by bug-dash-ops-8 (2026-09-25): the three installs used to land
    # in the same instant and the first replaced version was pruned at once,
    # which was the defect. A version is pruned by a later install only once
    # its own grace is over, so the clock moves past it here.
    clock = [1_000_000.0]
    monkeypatch.setattr(cli_tools.time, "time", lambda: clock[0])
    install_version(settings, "2.1.200")
    install_version(settings, "2.1.267")          # 2.1.200 replaced now
    clock[0] += cli_tools.PRUNE_GRACE_SECONDS + 1
    install_version(settings, "2.1.280")
    root = cli_tools.tool_root(settings, NAME)
    assert sorted(p.name for p in root.iterdir() if p.is_dir()
                  and p.name[0].isdigit()) == ["2.1.267", "2.1.280"]


def test_the_collector_tick_sweeps_even_with_the_feature_off(settings, conn):
    install_version(settings, "2.1.267")
    install_version(settings, "2.1.280")
    since = cli_tools.read_state(settings, NAME)["superseded_at_epoch"]
    cli_tools.auto_update_tick(conn, settings,
                               now=since + cli_tools.PRUNE_GRACE_SECONDS + 1,
                               spawn=run_now)
    assert not (cli_tools.tool_root(settings, NAME) / "2.1.267").exists()


def test_a_corrupt_updater_record_reads_as_empty(settings):
    path = cli_tools.auto_update_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2", encoding="utf-8")
    assert cli_tools.read_auto_update(settings) == {}


def test_the_record_is_json_beside_the_install_record(settings, conn, monkeypatch):
    enable(conn)
    install_version(settings, "2.1.280")
    publisher(monkeypatch, latest="2.1.280")
    cli_tools.auto_update_tick(conn, settings, now=NOW, spawn=run_now)
    path = cli_tools.auto_update_path(settings)
    assert path.parent == cli_tools.state_path(settings, NAME).parent
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["last_checked_epoch"] == NOW and data["result"] == "up_to_date"
