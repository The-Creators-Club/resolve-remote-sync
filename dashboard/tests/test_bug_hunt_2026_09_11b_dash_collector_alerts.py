"""bug hunt 2026-09-11b, dash-collector-alerts (CR-256).

One test per finding, each written to fail at f1eeb42. The theme is the same
one the hunt found everywhere: a fix that landed half of itself. A silence
spelled with a MUTATING call silenced the backstop too; a liveness flag with
one threshold made a Syncthing-less site permanently alarmed; a keep-list
rebuilt from the rows the same pass deletes survives exactly one pass; a
restore that refuses a truncated walk is still chosen from a preview that
shows the numbers the truncation invented.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, health, invariants, mount_status, recovery
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-09-11T12:00:00+00:00"


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        # The real collector thread races every direct scan call below,
        # exactly as test_alerts.py's fixture explains.
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        conn.execute("DELETE FROM alert_log")
        conn.execute("DELETE FROM notices")
        conn.execute("DELETE FROM poll_runs")
        conn.commit()
        try:
            yield client, conn, app.state.settings
        finally:
            conn.close()


# ------------------------------------------------ dash-collector-alerts-1 + -8
# (the alerts half; db.fetch_collector_status's threshold is dash-db's)

def _free_kind_runs(conn, minutes_ago):
    """What a Syncthing-less deployment's poll_runs look like: the three
    SYNCTHING_FREE_KINDS and nothing else."""
    base = dbmod.parse_iso(NOW)
    import datetime as dt
    for kind, age in zip(dbmod.SYNCTHING_FREE_KINDS, minutes_ago):
        at = (base - dt.timedelta(minutes=age)).isoformat()
        dbmod.record_poll_run(conn, kind, at, at, True, "")
    conn.commit()


def test_a_syncthing_less_site_whose_collector_is_turning_is_not_stopped(env):
    """prune 3600 s, invariants 900 s, alerts 600 s: the newest START on such
    a site is always older than the 180 s constant, so the stored flag is
    permanently True and the home page called a healthy collector STOPPED."""
    client, conn, settings = env
    assert not settings.syncthing_url
    _free_kind_runs(conn, (30, 15, 8))
    status = dbmod.fetch_collector_status(conn, now=NOW)
    assert status["collector_stale"] is True, "the flag under test is not raised"
    kinds = {f["kind"] for f in alerts.scan(conn, settings, NOW)}
    assert "collector_stale" not in kinds


def test_a_syncthing_less_site_whose_collector_really_stopped_still_says_so(env):
    client, conn, settings = env
    _free_kind_runs(conn, (600, 400, 100))
    kinds = {f["kind"] for f in alerts.scan(conn, settings, NOW)}
    assert "collector_stale" in kinds


def test_a_site_with_syncthing_keeps_the_three_minute_threshold(env):
    client, conn, settings = env
    with_st = Settings(db_path=settings.db_path, report_token="sekrit",
                       session_secret=SECRET, admin_users=frozenset({"owen"}),
                       syncthing_url="http://nas:8384")
    _free_kind_runs(conn, (30, 15, 8))
    kinds = {f["kind"] for f in alerts.scan(conn, with_st, NOW)}
    assert "collector_stale" in kinds


def test_the_duplicate_collector_liveness_query_is_gone(env):
    """dash-collector-alerts-8: `_collector_started_recently` re-ran
    `db.fetch_collector_status`'s own MAX(started_at) against the same
    constant, so it could never change the verdict."""
    assert not hasattr(alerts, "_collector_started_recently")


# ------------------------------------------------ dash-collector-alerts-2

def _ctx_for(conn, settings, editors, open_projects):
    """A real Ctx with the fields these two checks read filled in by hand.

    `Ctx.__init__` builds the whole fleet view from the database; the two
    checks under test read six of its attributes and the bug is in how one
    of them MUTATES another, so the parts are assembled directly.
    """
    ctx = object.__new__(alerts.Ctx)
    ctx.conn = conn
    ctx.settings = settings
    ctx.now = NOW
    ctx.editors = editors
    ctx.open_projects = open_projects
    ctx.plan_slugs = {}
    ctx.named = set()
    ctx._open_alert_subjects = {}
    ctx.projects = []
    # `_synced_project`'s three ways of tying a project name to the tree. All
    # empty: "Wedding Video" is the editor's own project, on their own disk.
    ctx.project_roots = {}
    ctx.tree_identity = {}
    ctx.tree_labels = {}
    return ctx


def test_a_quiet_out_of_tree_machine_can_still_reach_the_red_backstop(env):
    """A machine on a personal project AND red for three hours.

    `out_of_tree` deliberately says nothing about it. `red_unexplained` - the
    one check that exists to turn "green while dead" into a message - must
    still be able to, and could not, because the silence was spelled with
    `ctx.name(who)`, which adds the machine to `ctx.named`.
    """
    client, conn, settings = env
    editors = [{
        "editor_username": "jsmith", "machine": "EDIT-PC",
        "status": health.RED,
        "received_at": "2026-09-11T09:00:00+00:00",
        "lanes": [{"name": "lane_b_proxy_down", "state": "error",
                   "state_since": "2026-09-11T09:00:00+00:00"}],
        "guard": {"resolve_out_of_tree": 40},
        "why": {"sentence": ""},
    }]
    ctx = _ctx_for(conn, settings, editors, {"jsmith/EDIT-PC": "Wedding Video"})

    assert alerts._check_out_of_tree(ctx) == []
    assert "jsmith/EDIT-PC" not in ctx.named, \
        "a check that said nothing claimed the subject anyway"
    backstop = alerts._check_red_unexplained(ctx)
    assert [f["subject"] for f in backstop] == ["jsmith/EDIT-PC"]


def test_an_out_of_tree_machine_that_was_raised_is_still_named(env):
    """The other direction: the QUIET branch (a subject the ledger already
    holds open) emits a finding, so the backstop must leave it alone."""
    client, conn, settings = env
    dbmod.record_alert(conn, "out_of_tree", "jsmith/EDIT-PC", "b@example",
                       True, "sent", NOW)
    conn.commit()
    editors = [{
        "editor_username": "jsmith", "machine": "EDIT-PC",
        "status": health.RED,
        "received_at": "2026-09-11T09:00:00+00:00",
        "lanes": [{"name": "lane_b_proxy_down", "state": "error",
                   "state_since": "2026-09-11T09:00:00+00:00"}],
        "guard": {"resolve_out_of_tree": 40},
    }]
    ctx = _ctx_for(conn, settings, editors, {"jsmith/EDIT-PC": "Wedding Video"})
    if "jsmith/EDIT-PC" not in ctx.open_alert_subjects("out_of_tree"):
        pytest.skip("the alert ledger is not keyed the way this test assumes")
    found = alerts._check_out_of_tree(ctx)
    assert [f["subject"] for f in found] == ["jsmith/EDIT-PC"]
    assert found[0]["quiet"] is True
    assert alerts._check_red_unexplained(ctx) == []


# ------------------------------------------------ dash-collector-alerts-3

def test_a_truncated_invariant_keeps_its_hidden_subjects_past_pass_two(
        tmp_path, monkeypatch):
    """45 subjects broken, 20 visible per pass, and the window moves.

    `record_invariant_result` DELETES the subject rows a BROKEN pass did not
    name, and the keep-list is rebuilt from those same rows - so it only ever
    holds the PREVIOUS pass's 20. By the third window, the notices for the
    first twenty are closed as CLEARED while all 45 are still broken, which
    is the mistake the keep-list's own comment is written against.
    """
    import dataclasses

    invariants._TRUNCATED_CARRY.clear()
    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token="tok", admin_users=frozenset({"owen"}))
    inv = invariants.INVARIANTS[0]
    windows = [range(0, 20), range(20, 40), range(40, 45)]

    def check(_ctx):
        window = windows[min(check.pass_no, len(windows) - 1)]
        check.pass_no += 1
        return invariants.Outcome(
            invariants.BROKEN, "45 subject(s)",
            [(f"subject-{i}", "unshared") for i in window], truncated=True)

    check.pass_no = 0
    monkeypatch.setattr(invariants, "INVARIANTS",
                        [dataclasses.replace(inv, check=check)])
    try:
        for _ in windows:
            invariants.run_cycle(conn, settings, NOW)
        cleared = [str(r["subject"]) for r in conn.execute(
            "SELECT subject FROM notices WHERE kind='invariant_broken' "
            "AND cleared_at IS NOT NULL")]
        assert cleared == [], f"a still-broken subject was cleared: {cleared}"
        open_subjects = {str(r["subject"]) for r in conn.execute(
            "SELECT subject FROM notices WHERE kind='invariant_broken' "
            "AND cleared_at IS NULL")}
        assert f"{inv.key}: subject-0" in open_subjects
        assert f"{inv.key}: subject-44" in open_subjects
    finally:
        invariants._TRUNCATED_CARRY.clear()
        conn.close()


# ------------------------------------------------ dash-collector-alerts-4

def test_a_verdict_written_while_a_root_was_away_is_not_overwritten():
    """`_STATE` is not `recheck`'s: the ytdl feature gate rewrites its entry
    from a request thread. Replaying the boot verdict over that put MOUNTED
    back on a page that answers 404 to every request."""
    mount_status.reset()
    try:
        mount_status.record("ytdl", "mounted", "serving /data/ytdl")
        mount_status.record_root("ytdl", "/data/ytdl")
        mount_status.recheck(lambda _p: False)
        assert mount_status.get("ytdl")[0] == mount_status.DEGRADED

        # The admin turns [features] youtube_download off while it is away.
        mount_status.record("ytdl", "disabled", "youtube_download is off")

        mount_status.recheck(lambda _p: True)
        assert mount_status.get("ytdl")[0] == "disabled", \
            "the boot verdict was replayed over a newer one"
    finally:
        mount_status.reset()


def test_a_root_that_comes_back_still_restores_the_boot_verdict():
    mount_status.reset()
    try:
        mount_status.record("broll", "mounted", "serving /vault")
        mount_status.record_root("broll", "/vault")
        mount_status.recheck(lambda _p: False)
        assert mount_status.get("broll")[0] == mount_status.DEGRADED
        assert mount_status.recheck(lambda _p: True) == {
            "broll": ("mounted", "serving /vault")}
        assert mount_status.get("broll") == ("mounted", "serving /vault")
    finally:
        mount_status.reset()


# ------------------------------------------------ dash-collector-alerts-5

def test_the_registry_is_readable_while_a_root_is_being_probed():
    """A stat on a hung NFS/CIFS mount blocks in the kernel. Under `_LOCK`
    that parked `/api/v1/health` and the nav behind the collector thread."""
    mount_status.reset()
    release = threading.Event()
    reader_done = threading.Event()
    seen = []

    def slow_probe(_path):
        def read():
            seen.append(mount_status.snapshot())
            reader_done.set()

        t = threading.Thread(target=read, daemon=True)
        t.start()
        # The reader gets two seconds to take the lock this thread must not
        # be holding. It is a timeout, not a sleep: the fixed code sets the
        # event immediately.
        reader_done.wait(2.0)
        release.set()
        return True

    try:
        mount_status.record("cards", "mounted", "serving /cards-app")
        mount_status.record_root("cards", "/cards-app")
        mount_status.recheck(slow_probe)
        assert reader_done.is_set(), "a reader blocked behind the probe"
        assert seen and "cards" in seen[0]
    finally:
        mount_status.reset()


# ------------------------------------------------ dash-collector-alerts-6
# NOT A BUG (see the ledger): `heartbeat_due` has refused a no-sink site since
# CR-155..164 and never reaches the attempt ceiling there. Pinned, because the
# finding is exactly what removing that gate would look like.

def test_a_site_with_no_sink_writes_no_heartbeat_rows_at_all(env):
    client, conn, settings = env
    alerts.set_settings(conn, {"alerts_heartbeat": "1"}, "owen")
    conn.commit()
    assert (alerts.get_settings(conn).get("alerts_sink") or alerts.SINK_NONE) \
        == alerts.SINK_NONE
    assert alerts.heartbeat_due(conn, NOW) is False


# ------------------------------------------------ dash-collector-alerts-7

def _tiny_tree(tmp_path):
    projects = tmp_path / "projects"
    snaps = tmp_path / "snapshots"
    for rel in ("2026/One/a.txt", "2026/One/b.txt"):
        p = projects / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("live", encoding="utf-8")
    for rel in ("a.txt", "b.txt", "c.txt", "d.txt"):
        p = snaps / "ccsync-20260911-1100" / "2026/One" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("snap", encoding="utf-8")
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token="tok", admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    dbmod.upsert_project(conn, "one", "2026/One", "/x", NOW)
    conn.commit()
    return settings, conn, snaps


def test_a_preview_that_stopped_early_shows_no_counts(tmp_path, monkeypatch):
    """The restore refuses a truncated walk; the preview is where the owner
    DECIDES, and it was still showing the missing count the cap invented."""
    settings, conn, snaps = _tiny_tree(tmp_path)
    monkeypatch.setattr(recovery, "MAX_SCAN_FILES", 2)
    try:
        preview = recovery.preview_restore(
            settings, conn, "one", "ccsync-20260911-1100",
            env={recovery.ENV_SNAPSHOT_DIR: str(snaps)})
        assert preview["truncated"] is True
        assert preview["counts_unavailable"] is True
        assert preview["missing_count"] == 0 and preview["missing"] == []
        assert preview["missing_bytes"] == 0
        assert "more than" in preview["note"]
        # The template does arithmetic on these: they stay numbers.
        assert preview["missing_count"] >= len(preview["missing"])
    finally:
        conn.close()


def test_a_preview_that_walked_the_whole_tree_still_counts(tmp_path):
    settings, conn, snaps = _tiny_tree(tmp_path)
    try:
        preview = recovery.preview_restore(
            settings, conn, "one", "ccsync-20260911-1100",
            env={recovery.ENV_SNAPSHOT_DIR: str(snaps)})
        assert preview["truncated"] is False
        assert preview["counts_unavailable"] is False
        assert preview["missing_count"] == 2
        assert {m["rel"] for m in preview["missing"]} == {"c.txt", "d.txt"}
    finally:
        conn.close()


# ------------------------------------------------ regression-25

MON_0800 = "2026-09-07T08:00:00+00:00"
MON_0810 = "2026-09-07T08:10:00+00:00"
MON_0820 = "2026-09-07T08:20:00+00:00"
MON_0900 = "2026-09-07T09:00:00+00:00"
MON_1500 = "2026-09-07T15:00:00+00:00"


def test_a_sink_outage_over_the_weekly_slot_delays_the_report_not_deletes_it(env):
    """Three attempts at ten-minute cadence spend the per-slot ceiling in
    twenty minutes, and the week's report was then gone until next Monday."""
    client, conn, settings = env
    alerts.set_settings(conn, {"alerts_weekly": "1"}, "owen")
    conn.commit()
    for at in (MON_0800, MON_0810, MON_0820):
        dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "", False,
                           "smtp refused", at)
    conn.commit()

    # Still inside the backoff: the collector does not retry every cycle.
    assert alerts.weekly_due(conn, MON_0900) is False
    # ...and once it has elapsed, the relay being back sends the week's
    # report late rather than never.
    assert alerts.weekly_due(conn, MON_1500) is True


def test_a_weekly_that_was_sent_is_not_retried_by_the_backoff(env):
    client, conn, settings = env
    alerts.set_settings(conn, {"alerts_weekly": "1"}, "owen")
    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "b@example", True,
                       "sent", MON_0800)
    conn.commit()
    assert alerts.weekly_due(conn, MON_1500) is False


# =====================================================================
# Hand-off wave (the OWED lines wave 1 routed to this territory).
# =====================================================================

import datetime as _dt
import json as _json

from ccsync_dashboard import auth as _auth
from ccsync_dashboard import collector as _collector


def _report_headers(editor="jsmith", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": _auth.make_identity_token(SECRET, editor)}


def _report(guard=None, machine="EDIT-PC"):
    body = {
        "editor_name": "JSmith",
        "machine": machine,
        "companion_version": "0.9.71",
        "reported_at": NOW,
        "lanes": [
            {"name": "lane_b_proxy_down", "state": "idle", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None},
        ],
    }
    if guard is not None:
        body["sync_guard"] = guard
    return body


def _kinds(findings):
    return {f["kind"] for f in findings}


def _one(findings, kind):
    rows = [f for f in findings if f["kind"] == kind]
    assert rows, f"{kind} did not fire: {sorted(_kinds(findings))}"
    return rows[0]


def _iso_minus(now, seconds):
    return (dbmod.parse_iso(now) - _dt.timedelta(seconds=seconds)).isoformat()


# ------------------------------------------------- regression-11 (the reader)

SIDECAR_FAIL = {
    "at": NOW,
    "ytdlp": {
        "version": "2026.09.01", "action": "checked", "ok": True,
        "stale": False, "checked_at": NOW,
        "sidecar": {
            "ok": False, "action": "failed", "failed": ["ffmpeg", "ffprobe"],
            "cause": "certificate verify failed: unable to get local issuer "
                     "certificate",
            "consecutive_failures": 4,
            "message": "could not install ffmpeg",
            "checked_at": NOW,
        },
    },
}


def _post_guard(client, guard, machine="EDIT-PC"):
    r = client.post("/api/v1/report", json=_report(guard, machine),
                    headers=_report_headers())
    assert r.status_code == 200, r.text
    return r


def test_a_failing_media_sidecar_reaches_the_alerts_page(env):
    """regression-11: the companion has reported which tool failed and why
    since 0.9.71, `_store_ytdlp_state` swallowed it into the `ytdlp:` meta
    blob, and NOTHING on this server read it. `why` answered
    `no_capable_machine` and the cause lived in one editor's tray."""
    client, conn, settings = env
    _post_guard(client, SIDECAR_FAIL)
    finding = _one(alerts.scan(conn, settings, NOW), "media_sidecar_failed")
    assert "ffmpeg" in finding["diagnosis"]
    assert "certificate verify failed" in finding["diagnosis"]
    assert "EDIT-PC" in finding["subject"]
    assert finding["severity"] == alerts.SEV_WARN


def test_one_failed_sidecar_check_is_not_yet_a_finding(env):
    """The installer retries and a flaky network heals itself on the next
    daily check; two in a row is a machine that needs somebody."""
    client, conn, settings = env
    guard = _json.loads(_json.dumps(SIDECAR_FAIL))
    guard["ytdlp"]["sidecar"]["consecutive_failures"] = 1
    _post_guard(client, guard)
    assert "media_sidecar_failed" not in _kinds(alerts.scan(conn, settings, NOW))


def test_a_companion_too_old_to_send_a_sidecar_block_is_silent(env):
    """ABSENT is "it has not said", which must never read as "it is fine":
    silence here, and `cap_ffmpeg` on the jobs page answers for those."""
    client, conn, settings = env
    guard = _json.loads(_json.dumps(SIDECAR_FAIL))
    guard["ytdlp"].pop("sidecar")
    _post_guard(client, guard)
    assert "media_sidecar_failed" not in _kinds(alerts.scan(conn, settings, NOW))


# ------------------------------------------------- comp-ytdl-jobs-1 (the row)

def _refusal(conn, at, version="0.9.65"):
    conn.execute(
        "UPDATE machine_state SET upgrade_refused_version=?, "
        "upgrade_refused_reason=?, upgrade_refused_at=?",
        (version, "the offered build is below this machine's downgrade floor",
         at))
    conn.commit()


def test_a_refusal_nobody_is_restamping_stops_alarming(env):
    """comp-ytdl-jobs-1's other side. The companion re-stamps `refused_at`
    every time it turns an offer down, so an OLD stamp means nothing is being
    offered and refused any more. On 0.9.65..0.9.71 the standing refusal only
    cleared by taking a LATER offer, which a machine already running the
    current build is never given: `[ REFUSING 0.9.65 ]` and this alert stayed
    lit for the life of the tray process after the admin had already put the
    newer build back."""
    client, conn, settings = env
    _post_guard(client, {"at": NOW})
    _refusal(conn, _iso_minus(NOW, alerts.UPGRADE_REFUSED_STALE_SECONDS + 60))
    assert "upgrade_refused" not in _kinds(alerts.scan(conn, settings, NOW))


def test_a_refusal_that_is_being_restamped_still_alarms(env):
    client, conn, settings = env
    _post_guard(client, {"at": NOW})
    _refusal(conn, _iso_minus(NOW, 300))
    finding = _one(alerts.scan(conn, settings, NOW), "upgrade_refused")
    assert "0.9.65" in finding["diagnosis"]


# ------------------------------------------------- res-fleet-3 (the other half)

def _code(monkeypatch, source, applied, refused="", running=None):
    from ccsync_dashboard import dashboard_update

    monkeypatch.setattr(dashboard_update, "running_source", lambda _s: source)
    monkeypatch.setattr(
        dashboard_update, "_read_json",
        lambda _p: {"version": applied, "applied_at": NOW,
                    "revert_refused_reason": refused})
    if running is not None:
        monkeypatch.setattr(dashboard_update, "VERSION", running)


def test_a_container_booting_the_image_over_an_applied_tree_is_reported(
        env, monkeypatch):
    """res-fleet-3: dash-mounts-ui-8 moved the boot counter below
    `check_tree`, so a PERMANENT refusal never accumulates to the two boots
    that produced a revert with a sentence on the page. The container then
    boots the image every restart, for ever, while `current.json` still names
    the applied version - and nothing anywhere read `running_source` or
    `reverted_reason`."""
    client, conn, settings = env
    _code(monkeypatch, "image", "0.7.43", refused="its runtime id is not ours",
          running="0.7.30")
    finding = _one(alerts.scan(conn, settings, NOW), "code_not_applied")
    assert "0.7.43" in finding["diagnosis"] and "0.7.30" in finding["diagnosis"]
    assert "runtime id" in finding["diagnosis"]
    assert finding["severity"] == alerts.SEV_ERROR


def test_the_applied_tree_answering_is_not_a_finding(env, monkeypatch):
    client, conn, settings = env
    _code(monkeypatch, "volume", "0.7.43", running="0.7.43")
    assert "code_not_applied" not in _kinds(alerts.scan(conn, settings, NOW))
    # A developer's checkout says nothing about a deployment...
    _code(monkeypatch, "checkout", "0.7.43", running="0.7.30")
    assert "code_not_applied" not in _kinds(alerts.scan(conn, settings, NOW))
    # ...and an image that has CAUGHT UP is how a bundle is meant to retire.
    _code(monkeypatch, "image", "0.7.43", running="0.7.43")
    assert "code_not_applied" not in _kinds(alerts.scan(conn, settings, NOW))
    # Nothing applied at all is an ordinary image-mode deployment.
    _code(monkeypatch, "image", "", running="0.7.43")
    assert "code_not_applied" not in _kinds(alerts.scan(conn, settings, NOW))


def test_a_current_json_this_server_cannot_read_raises_nothing(env, monkeypatch):
    """"Could not ask" is never an alarm about what the file says."""
    client, conn, settings = env
    from ccsync_dashboard import dashboard_update

    def _boom(_p):
        raise OSError("permission denied")

    monkeypatch.setattr(dashboard_update, "_read_json", _boom)
    assert "code_not_applied" not in _kinds(alerts.scan(conn, settings, NOW))


def test_both_new_kinds_are_registered_with_their_writers(env):
    """A registered kind with no writer was a prior build's own bug, and a
    writer with no registry row is a kind nobody is told about: the dedup, the
    recovery message, the Alerts page and the weekly report's "checked and
    found nothing wrong" list all come from the row."""
    _client, conn, settings = env
    by_name = {k.kind: k for k in alerts.ALERT_KINDS}
    for kind, writer in (("media_sidecar_failed", alerts._check_media_sidecar_failed),
                         ("code_not_applied", alerts._check_code_not_applied)):
        assert kind in by_name, kind
        assert by_name[kind].check is writer
        assert by_name[kind].what
    _subject, body = alerts.compose_weekly(conn, NOW, settings)
    assert "each computer's ffmpeg/ffprobe/deno sidecar" in body
    assert "which code this container booted" in body


# ------------------------------------------------- dash-mounts-ui-b-1

def test_a_mount_may_name_a_file_as_its_witness(env, tmp_path):
    """A bind mount that goes away LEAVES ITS MOUNT POINT BEHIND, so probing
    the root is probing a directory that is there either way. Music's root
    holds `music.db` and nothing else the mount creates, so the only honest
    witness is a FILE - which `os.path.isdir` reported as degraded on every
    healthy deployment."""
    root = tmp_path / "music-data"
    root.mkdir()
    witness = root / "music.db"
    witness.write_text("x")
    mount_status.reset()
    try:
        mount_status.record("music", mount_status.MOUNTED, "serving /music")
        mount_status.record_root("music", str(root), witness=str(witness))
        assert mount_status.recheck() == {}, "a healthy mount was downgraded"

        # The export goes; the mount point stays behind.
        witness.unlink()
        assert root.is_dir()
        changed = mount_status.recheck()
        assert changed.get("music", ("", ""))[0] == mount_status.DEGRADED
        assert str(root) in changed["music"][1], "the sentence names the mount"
    finally:
        mount_status.reset()


def test_a_mount_with_no_witness_still_probes_its_root(env, tmp_path):
    """Every caller but music records a directory; the witness is optional
    and an older caller must keep working."""
    root = tmp_path / "vault"
    root.mkdir()
    mount_status.reset()
    try:
        mount_status.record("broll", mount_status.MOUNTED, "serving /broll")
        mount_status.record_root("broll", str(root))
        assert mount_status.recheck() == {}
        root.rmdir()
        got = mount_status.recheck().get("broll", ("", ""))[0]
        assert got == mount_status.DEGRADED
    finally:
        mount_status.reset()


# ------------------------------------------------- dash-db-4

def test_the_enforce_cycle_asks_for_the_enforce_view(monkeypatch, conn):
    """`for_enforce` is named after this cycle and this cycle did not pass it,
    so "what should this machine hold" was computed by TWO rules - the map and
    CR-110's belt further down the same function - that agree only because the
    belt happens to exist. The belt stays; the read now asks the same question
    the two admin-facing readers ask."""
    from fake_syncthing import FakeSyncthing
    from ccsync_dashboard.syncthing_client import SyncthingClient

    seen = []
    real = dbmod.fetch_machine_selections

    def spy(c, *a, **kw):
        seen.append(kw.get("for_enforce", False))
        return real(c, *a, **kw)

    monkeypatch.setattr(_collector.db, "fetch_machine_selections", spy)
    server = FakeSyncthing().start()
    try:
        c = _collector.Collector(
            Settings(syncthing_url=server.url, syncthing_api_key="k"),
            client=SyncthingClient(server.url, "k", timeout=5))
        c.run_cycle(conn, ["config", "enforce"])
    finally:
        server.stop()
    assert seen and all(seen), "the enforce cycle still reads the admin view"
