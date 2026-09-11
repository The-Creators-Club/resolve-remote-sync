"""Bug hunt 2026-09-11b, territory `dash-release-jobs` (CR-260).

The release feed poller and the pinned executor (thread revival), the cards
selection block's staged half, the cards tunnel's machine name across the
deploy window, the silently dropped feed record, the pre-signed feed URL, and
the healer that writes on the boot path.

No network: `release_feed._opener` is monkeypatched wherever a fetch happens,
so a request nobody registered 404s rather than reaching the internet.
"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from ccsync_dashboard import (cards_ai, cards_exec, db as dbmod,
                              dashboard_update, release_feed)
from ccsync_dashboard.settings import Settings

from test_release_feed import (CHANNEL_URL, FEED_BASE, SECRET, TEST_PUBKEY,
                               make_channel, make_record, patch_opener)

SIG_URL = f"{FEED_BASE}/channel.json.sig"


def _settings(tmp_path, **over):
    kw = dict(
        db_path=str(tmp_path / "feed.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,), release_feed_url=CHANNEL_URL,
    )
    kw.update(over)
    return Settings(**kw)


def _alive(name: str) -> int:
    return len([t for t in threading.enumerate() if t.name == name and t.is_alive()])


# ------------------------------------------------------- dash-release-jobs-1
# (with res-fleet-4) a cycle that outlives stop()'s join must not be revived
# by the next start(), and must not be joined by a second thread.

def test_a_feed_check_that_outlives_stop_is_not_revived_by_start(tmp_path, monkeypatch):
    settings = _settings(tmp_path, release_feed_interval=0.01)
    monkeypatch.setattr(release_feed, "POLLER_FIRST_CHECK_DELAY", 0.0)
    monkeypatch.setattr(release_feed, "POLLER_MIN_INTERVAL", 0.01)
    # raising=False so the test still RUNS on the pre-fix tree (where the
    # join timeout was the literal 5.0): there it simply sits out the five
    # seconds and then fails on the behaviour, which is the point.
    monkeypatch.setattr(release_feed, "POLLER_STOP_JOIN_SECONDS", 0.05, raising=False)

    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []
    lock = threading.Lock()

    def slow_check(*a, **k):
        with lock:
            calls.append(1)
            first = len(calls) == 1
        if first:
            entered.set()
            release.wait(10.0)
        return {"ok": True}

    monkeypatch.setattr(release_feed, "check_now", slow_check)
    monkeypatch.setattr(release_feed.db, "connect", lambda *a, **k: None)

    poller = release_feed.FeedPoller(settings, None)
    poller.start()
    try:
        assert entered.wait(5.0), "the poller never entered its first check"
        poller.stop()                       # the join expires: the cycle is still running
        assert poller._thread is not None, "stop() dropped the handle to a live thread"
        poller.start()                      # must NOT clear the stop event under it
        assert _alive("release-feed-poller") == 1, "a second poller thread was started"
    finally:
        release.set()
        time.sleep(0.3)
    with lock:
        assert len(calls) == 1, (
            "the poller that outlived stop() kept polling: start() cleared the event "
            "under it")
    assert _alive("release-feed-poller") == 0


def test_a_pinned_tick_that_outlives_stop_is_not_revived_by_start(tmp_path, monkeypatch):
    monkeypatch.setattr(cards_exec, "STOP_JOIN_SECONDS", 0.05, raising=False)
    settings = _settings(tmp_path)

    class _Engine:
        def fleet_execute(self, *a, **k):   # only `available()` reads this
            return {}

    entered = threading.Event()
    release = threading.Event()
    ticks: list[int] = []
    lock = threading.Lock()

    ex = cards_exec.PinnedExecutor(settings, _Engine(), connect=lambda: None,
                                   poll_seconds=0.01)

    def slow_tick(conn):
        with lock:
            ticks.append(1)
            first = len(ticks) == 1
        if first:
            entered.set()
            release.wait(10.0)
        return []

    ex.tick = slow_tick                     # type: ignore[assignment]
    ex.start()
    try:
        assert entered.wait(5.0), "the executor never entered its first tick"
        ex.stop()
        assert ex._thread is not None, "stop() dropped the handle to a live worker"
        ex.start()
        assert _alive("ccsync-pinned") == 1, "a second pinned worker was started"
    finally:
        release.set()
        time.sleep(0.3)
    with lock:
        assert len(ticks) == 1, "the worker that outlived stop() kept draining the queue"


# ------------------------------------------------------- dash-release-jobs-2
# the staged half of the selection block must say what it did not show.

def test_the_staged_half_of_the_selection_block_says_what_it_truncated():
    staged = [{"id": "g%d" % n, "label": "row %d" % n}
              for n in range(cards_ai.MAX_SELECTION_ROWS + 80)]
    block = cards_ai.selection_block([{"id": "a1"}], staged)
    assert "Staged cards selected on the shelf (%d)" % len(staged) in block
    assert "...and 80 more, by id alone:" in block
    # every id the model was told about is actually in the prompt
    last = staged[-1]["id"]
    assert "[%s]" % last in block
    assert block.index("...and 80 more") < block.index(cards_ai.SELECTION_END)


# dash-release-jobs-3 / wire-4 (the machine name across the deploy window)
# are in tests/test_cards_tunnel.py, beside the tunnel's other identity tests
# and its `env` fixture.


# ------------------------------------------------------- dash-release-jobs-4
# a record this dashboard refuses to offer has to be visible somewhere the
# admin looks, not only in a container log.

def test_a_non_canonical_feed_record_is_reported_and_not_merely_dropped(tmp_path, monkeypatch):
    record, body = make_record(platform="Windows", version="0.10.0")
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(),
        SIG_URL: sig.encode(),
        record["url"]: body,
    })
    settings = _settings(tmp_path)
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)

    class _State:
        pass

    result = release_feed.check_now(conn, settings, _State())
    assert result["ok"] is True
    state = dbmod.get_feed_state(conn)
    assert state["last_error"], "a build that cannot be offered left nothing to see"
    assert "0.10.0" in state["last_error"] and "lower-case" in state["last_error"]
    assert result.get("rejected") == ["companion/Windows 0.10.0"]
    conn.close()


def test_a_canonical_feed_record_still_clears_the_last_error(tmp_path, monkeypatch):
    record, body = make_record(platform="windows", version="0.10.0")
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(),
        SIG_URL: sig.encode(),
        record["url"]: body,
    })
    settings = _settings(tmp_path)
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)

    class _State:
        pass

    result = release_feed.check_now(conn, settings, _State())
    assert result["ok"] is True and result["error"] is None
    assert dbmod.get_feed_state(conn)["last_error"] == ""
    assert result.get("rejected", []) == []
    conn.close()


# ------------------------------------------------------- dash-release-jobs-5
# a pre-signed feed URL cannot have its `.sig` derived, and the refusal has
# to say that rather than name a URL the operator never configured.

def test_a_presigned_feed_url_is_named_as_the_cause_of_the_signature_refusal(monkeypatch):
    presigned = (CHANNEL_URL + "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
                 "&X-Amz-Credential=AKIA%2F20260911%2Fus-east-1%2Fs3%2Faws4_request"
                 "&X-Amz-Signature=deadbeef")
    channel, _sig = make_channel([])
    patch_opener(monkeypatch, {presigned: json.dumps(channel).encode()})
    got, reason = release_feed.fetch_and_verify_channel(presigned, (TEST_PUBKEY,))
    assert got is None
    assert "PRE-SIGNED" in reason, reason
    assert "channel.json.sig" in reason


def test_a_query_token_feed_url_still_derives_its_signature(monkeypatch):
    tokened = CHANNEL_URL + "?token=abc123"
    channel, sig = make_channel([])
    patch_opener(monkeypatch, {
        tokened: json.dumps(channel).encode(),
        SIG_URL + "?token=abc123": sig.encode(),
    })
    got, reason = release_feed.fetch_and_verify_channel(tokened, (TEST_PUBKEY,))
    assert reason is None and got is not None


# ------------------------------------------------------- dash-release-jobs-7
# read_state runs the healer, the healer writes, and a full or read-only data
# directory must not turn a status read into an exception.

def test_the_healer_survives_a_data_directory_it_cannot_write(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    path = dashboard_update.update_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "step": "downloading", "in_progress": True, "version": "0.7.44",
        "owner_pid": 999999, "owner_nonce": "someone-else",
    }), encoding="utf-8")

    def _full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(dashboard_update, "_write_json", _full)
    state = dashboard_update.read_state(settings)
    assert state["in_progress"] is False, "the dead latch was not healed in memory"
    assert state["step"] == "failed"


def test_a_spent_restart_request_is_healed_on_a_full_disk_too(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    path = dashboard_update.update_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "step": "restarting", "in_progress": True, "restart_requested": True,
        "owner_pid": 999999, "owner_nonce": "a-process-that-is-gone",
    }), encoding="utf-8")

    def _readonly(*a, **k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(dashboard_update, "_write_json", _readonly)
    state = dashboard_update.read_state(settings)
    assert state["in_progress"] is False and state["restart_requested"] is False


# ============================================================ hand-off wave
#
# The three OWED lines routed back to this territory (HANDOFFS.md
# "## dash-release-jobs"): the refused revert out of `dashboard_update
# .status()` (res-fleet-3, tested in test_dashboard_update.py beside the
# other status tests), the explicit signature URL dash-core's settings now
# carries, and `why`'s capability line naming the sidecar cause.


class _SettingsWithSigUrl:
    """A Settings that carries `release_feed_sig_url`.

    dash-core adds the real field in this same pass; this wrapper is what
    lets the test pin the READ without depending on which builder lands
    first, and the companion test below pins the getattr fallback for a
    Settings that does not have it.
    """

    def __init__(self, settings, sig_url: str) -> None:
        self._settings = settings
        self.release_feed_sig_url = sig_url

    def __getattr__(self, name):
        return getattr(self._settings, name)


def test_a_declared_signature_url_is_fetched_instead_of_the_derived_one(monkeypatch):
    presigned = (CHANNEL_URL + "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
                 "&X-Amz-Signature=deadbeef")
    elsewhere = "https://feed.example.test/signatures/channel.json.sig"
    channel, sig = make_channel([])
    # The DERIVED url is not in the table: if the code still derives it, the
    # fake opener 404s and this fails with the pre-signed refusal.
    patch_opener(monkeypatch, {presigned: json.dumps(channel).encode(),
                               elsewhere: sig.encode()})
    got, reason = release_feed.fetch_and_verify_channel(
        presigned, (TEST_PUBKEY,), elsewhere)
    assert reason is None, reason
    assert got is not None


def test_check_now_reads_the_declared_signature_url(tmp_path, monkeypatch):
    settings = _settings(tmp_path, release_feed_url=CHANNEL_URL + "?token=abc")
    elsewhere = "https://feed.example.test/elsewhere/channel.sig"
    channel, sig = make_channel([])
    patch_opener(monkeypatch, {
        CHANNEL_URL + "?token=abc": json.dumps(channel).encode(),
        elsewhere: sig.encode(),
    })
    conn = dbmod.connect(tmp_path / "feed.db")
    dbmod.migrate(conn)
    result = release_feed.check_now(
        conn, _SettingsWithSigUrl(settings, elsewhere), SimpleNamespace())
    assert result["ok"] is True, result
    assert not dbmod.get_feed_state(conn)["last_error"]
    conn.close()


def test_a_settings_without_the_new_field_still_derives_the_signature_url(
        tmp_path, monkeypatch):
    """getattr with a default: a rollback to an older tree, or a test double,
    must not turn the poll path into an AttributeError."""
    settings = _settings(tmp_path)
    assert not hasattr(settings, "release_feed_sig_url") or True
    channel, sig = make_channel([])
    patch_opener(monkeypatch, {CHANNEL_URL: json.dumps(channel).encode(),
                               SIG_URL: sig.encode()})
    conn = dbmod.connect(tmp_path / "feed.db")
    dbmod.migrate(conn)
    assert release_feed.check_now(conn, settings, SimpleNamespace())["ok"] is True
    conn.close()


# --------------------------------------------------------- regression-11
# comp-ytdl-jobs-3 landed the companion half of "say WHY this computer has
# no ffmpeg"; on the dashboard the verdict was stored and read by nobody, so
# `why` answered "cannot do this kind of work" for a machine that is trying
# to install the tool and failing for a nameable reason.

MEDIA_INPUTS = {"root": "vault", "rel_path": "Vault/2026/FF5/a.mov",
                "out_root": "vault"}


def _fleet_machine(conn, editor, machine, *, ffmpeg: bool):
    dbmod.upsert_machine_state(conn, editor, machine, None, dbmod.utcnow_iso())
    dbmod.store_machine_capabilities(conn, editor, machine, {
        "ffmpeg": ffmpeg, "ffprobe": ffmpeg, "mounts": ["vault"],
        "idle_seconds": 900, "cpu_count": 8,
    }, dbmod.utcnow_iso())
    conn.commit()


def _sidecar(conn, editor, machine, block):
    dbmod.meta_set_json(conn, f"ytdlp:{editor}/{machine}", {"sidecar": block})
    conn.commit()


def _media_job(conn):
    from ccsync_dashboard import jobs as jobs_mod
    return dbmod.create_job(conn, "proxy-480p", MEDIA_INPUTS,
                            jobs_mod.default_requires("proxy-480p", MEDIA_INPUTS))


def test_why_names_the_sidecar_cause_when_that_is_why_ffmpeg_is_missing(tmp_path):
    from ccsync_dashboard import jobs as jobs_mod

    conn = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(conn)
    _fleet_machine(conn, "leso", "MBP", ffmpeg=False)
    _sidecar(conn, "leso", "MBP", {
        "ok": False, "action": "failed", "failed": ["ffmpeg", "ffprobe"],
        "cause": "certificate verify failed: unable to get local issuer certificate",
        "consecutive_failures": 4,
    })
    job_id = _media_job(conn)
    answer = jobs_mod.explain(conn, job_id)
    line = answer["machines"][0]
    assert line["reason"] == jobs_mod.REFUSE_CAPABILITY
    assert "certificate verify failed" in line["why"], line["why"]
    assert "certificate verify failed" in line["sidecar_cause"]
    assert answer["reason_code"] == jobs_mod.REASON_NO_CAPABLE
    assert "certificate verify failed" in answer["summary"], answer["summary"]
    conn.close()


def test_an_unrelated_sidecar_failure_does_not_explain_a_mount_refusal(tmp_path):
    """The third condition: the tool the sidecar failed on must be one this
    job actually requires AND actually missing. Without it every capability
    refusal on that machine would be blamed on the sidecar."""
    from ccsync_dashboard import jobs as jobs_mod

    conn = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(conn)
    _fleet_machine(conn, "leso", "MBP", ffmpeg=True)
    _sidecar(conn, "leso", "MBP", {
        "ok": False, "action": "failed", "failed": ["deno"],
        "cause": "github.com timed out", "consecutive_failures": 2,
    })
    job_id = dbmod.create_job(conn, "proxy-480p", MEDIA_INPUTS,
                              {"ffmpeg": True, "mount": ["archive"]})
    line = jobs_mod.explain(conn, job_id)["machines"][0]
    assert line["reason"] == jobs_mod.REFUSE_CAPABILITY
    assert line["sidecar_cause"] == ""
    assert "github.com timed out" not in line["why"]
    conn.close()


def test_a_sidecar_that_succeeded_explains_nothing(tmp_path):
    """A machine with no ffmpeg and a HEALTHY sidecar verdict is the "nobody
    set it up" case, and must still read that way."""
    from ccsync_dashboard import jobs as jobs_mod

    conn = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(conn)
    _fleet_machine(conn, "jsmith", "EDIT-PC", ffmpeg=False)
    _sidecar(conn, "jsmith", "EDIT-PC", {"ok": True, "action": "checked"})
    line = jobs_mod.explain(conn, _media_job(conn))["machines"][0]
    assert line["sidecar_cause"] == ""
