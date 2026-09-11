"""The hand-off wave of the 2026-09-11b fix pass, territory dash-mounts-ui.

Seven items other builders finished half of and routed here, because the other
half is a template, a mount or a UI call site - all of which are this
territory's alone. Every test fails before the change it pins:

  security-1    a suspended freelancer's laptop was still stamped as that
                editor by all three mounts, so it could claim and write.
  dash-api-1    [ ROLL THE FLEET BACK ]'s htmx twin read the DEFAULT soak
                minutes, not this site's, so a site with the gate off was
                refused the re-pointing the JSON route performs.
  dash-api-4    the per-machine queue view was unreachable from the two
                templates that render it.
  dash-collector-alerts  a preview that could NOT count rendered "0 file(s)
                missing from the server now".
  dash-db-5     an unreadable archived list rendered as no archived projects.
  broll-5       a client-folder ledger locked for two seconds at boot marked
                the WHOLE /broll mount degraded.
  regression-11 the stored `ytdlp.sidecar` cause had no reader anywhere.
"""
from __future__ import annotations

import sqlite3
import sys
import types

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from ccsync_dashboard import api as api_mod
from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from test_broll_fleet_stamp import _build_fake_broll
from test_music_fleet_stamp import _build_fake_musicweb
from test_ytdl_mount import _build_fake_ytdlweb

SECRET = "s" * 32
SHARED = "f" * 40
INGEST = "9f3c1ab27d4e5608bc19af730d25e8641c07b9a3f2de5061"
FLEET_UID = "0123456789abcdef0123456789abcdef"
NOW = "2026-09-11T09:00:00+00:00"


def _known(conn, editor="editor2"):
    """A per-editor token for `editor`, who is therefore a known editor."""
    dbmod.record_known_editor(conn, editor, "admin")
    token, _row = dbmod.create_editor_report_token(conn, editor, created_by="admin")
    conn.commit()
    return token


def _suspend(conn, editor="editor2"):
    assert dbmod.suspend_editor(conn, editor, by="admin", reason="left the studio")
    conn.commit()


# --------------------------------------------------------------- security-1
# The three mounted fleet APIs mint `X-CCSync-Fleet-Auth: editor:<name>` from a
# `cce1.` token. DCORE-4 revokes no token when an account is suspended, so
# until now the ONE door suspension closed was /report: the same laptop could
# still claim an ingest batch, take a music library re-score, or pull a
# download into the shared tree. The stamp is what authorises all three, so
# withholding it is the refusal - the sub-app then falls back to its own
# shared-secret compare, which a cce1 token never matches.

@pytest.fixture
def broll_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "brolldata"))
    monkeypatch.setenv("BROLL_INGEST_TOKEN", INGEST)
    for name, module in _build_fake_broll(tmp_path).items():
        monkeypatch.setitem(sys.modules, name, module)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=SHARED, broll_enabled=True,
                        broll_ingest_token=INGEST,
                        admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def test_a_suspended_editors_laptop_is_not_stamped_by_the_broll_mount(broll_env):
    client, conn = broll_env
    token = _known(conn)
    path = f"/broll/api/fleet/ingest/batches/{FLEET_UID}/claim"
    first = client.post(path, json={}, headers={"X-CCSync-Token": token},
                        follow_redirects=False)
    assert first.status_code == 200, first.text
    assert first.json()["fleet_auth"] == "editor:editor2", "the control"

    _suspend(conn)
    after = client.post(path, json={}, headers={"X-CCSync-Token": token},
                        follow_redirects=False)
    # Either the gate turns it away or the stamp is withheld; what must never
    # happen is the sub-app being told this is editor2 in good standing.
    assert after.status_code != 200 or after.json()["fleet_auth"] is None


@pytest.fixture
def music_env(tmp_path, monkeypatch):
    for name, module in _build_fake_musicweb(tmp_path).items():
        monkeypatch.setitem(sys.modules, name, module)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=SHARED, admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def test_a_suspended_editors_laptop_is_not_stamped_by_the_music_mount(music_env):
    client, conn = music_env
    token = _known(conn)
    path = f"/music/api/fleet/ingest/batches/{FLEET_UID}/claim"
    first = client.post(path, json={}, headers={"X-CCSync-Token": token},
                        follow_redirects=False)
    assert first.status_code == 200, first.text
    assert first.json()["fleet_auth"] == "editor:editor2", "the control"

    _suspend(conn)
    after = client.post(path, json={}, headers={"X-CCSync-Token": token},
                        follow_redirects=False)
    assert after.status_code != 200 or after.json()["fleet_auth"] is None


@pytest.fixture
def ytdl_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YTDL_DATA_ROOT", str(tmp_path / "ytdldata"))
    monkeypatch.setenv("YTDL_PROJECTS_ROOT", str(tmp_path / "projects"))
    modules = _build_fake_ytdlweb()
    ytdl_app = modules["ytdlweb.main"].app

    @ytdl_app.post("/api/jobs/{job_id}/claim")
    def claim(job_id: int, request: Request) -> dict:
        # The fake's own routes echo X-CCSync-User; this one echoes the fleet
        # stamp, which is what authorises a claim made with no browser open.
        return {"fleet_auth": request.headers.get("x-ccsync-fleet-auth")}

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=SHARED, site_feature_youtube_download=True,
                        admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def test_a_suspended_editors_laptop_is_not_stamped_by_the_ytdl_mount(ytdl_env):
    client, conn = ytdl_env
    token = _known(conn)
    path = "/ytdl/api/jobs/1/claim"
    first = client.post(path, json={}, headers={"X-CCSync-Token": token},
                        follow_redirects=False)
    assert first.status_code == 200, first.text
    assert first.json()["fleet_auth"] == "editor:editor2", "the control"

    _suspend(conn)
    after = client.post(path, json={}, headers={"X-CCSync-Token": token},
                        follow_redirects=False)
    assert after.status_code != 200 or after.json()["fleet_auth"] is None


# ------------------------------------------------------- dash-api-1 (the UI half)

@pytest.fixture
def dash_env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects),
        report_token=SHARED, packages_dir=str(tmp_path / "pkgs"),
        release_soak_minutes=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn, settings
        conn.close()


def _admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def _publish_rows(conn):
    for version in ("0.9.64", "0.9.66"):
        dbmod.insert_companion_package(
            conn, version=version, platform="windows", filename=f"c{version}.exe",
            sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW,
            signature="sig", pubkey_id="k1")
    dbmod.set_current_package(conn, "windows", "0.9.66", "companion")
    conn.commit()


def _roll_back(client):
    return _admin(client).post(
        "/partials/admin/packages/roll-fleet-back",
        data={"platform": "windows", "from_version": "0.9.66",
              "to_version": "0.9.64"})


def test_the_rollback_button_reads_this_sites_soak_minutes(dash_env):
    """`[releases] soak_minutes = 0` is the documented way to turn the gate
    off, and the htmx twin passed no settings at all, so it read the DEFAULT
    and refused to re-point `current` on a site that had switched the gate
    off. The channel then went on handing out the build being rolled off."""
    client, conn, _settings = dash_env
    _publish_rows(conn)
    resp = _roll_back(client)
    assert resp.status_code == 200, resp.text
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.9.64"


def test_the_page_says_when_current_was_left_where_it_was(tmp_path):
    """The refusal is not an error - the fan-out happened - so it is not
    raised, and nothing rendered it: the admin read a silent success over a
    fleet still being offered the build they just rolled off."""
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), projects_dir=str(projects),
                        report_token=SHARED, packages_dir=str(tmp_path / "pkgs"))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        _publish_rows(conn)
        resp = _roll_back(client)
        assert resp.status_code == 200, resp.text
        # The soak gate is at its default here, and 0.9.64 has never run
        # anywhere, so `current` is left alone. The page has to say so.
        assert dbmod.get_current_package(conn, "windows")["version"] == "0.9.66"
        assert "0.9.64" in resp.text
        assert "no computer has reported" in resp.text
        conn.close()


# ------------------------------------------------------- dash-api-4 (the UI half)

def _report(client, editor="jsmith", machine="EDIT-PC", **extra):
    body = {"editor_name": editor, "machine": machine,
            "companion_version": "0.9.71", "platform": "windows",
            "reported_at": dbmod.utcnow_iso(),
            "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
    body.update(extra)
    return client.post("/api/v1/report", json=body,
                       headers={"X-CCSync-Token": SHARED,
                                "X-CCSync-Identity":
                                    auth.make_identity_token(SECRET, editor)})


def _as_editor(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


DESKTOP = "THE IMAC PROJECT"
LAPTOP = "THE LAPTOP PROJECT"


def _two_computers(client):
    """One person, two computers, each with a different project open.

    Nothing here depends on which reported LAST: `reported_at` is clamped to
    the server's clock on receipt, so two reports in one test are a tie, and a
    test that pinned "the newest wins" would be pinning a coin toss. Each page
    is asked about a named computer and must answer about that one.
    """
    _report(client, machine="IMAC", resolve_project=DESKTOP)
    _report(client, machine="MACBOOK", resolve_project=LAPTOP)


def test_the_queue_panel_can_be_asked_about_one_computer(dash_env):
    """dash-api-4 made build_queue_view per-machine; the two templates that
    render it both called it with no machine, so the fix was unreachable and
    an editor with two computers still read whichever reported last."""
    client, conn, _settings = dash_env
    _two_computers(client)

    for machine, mine, theirs in (("IMAC", DESKTOP, LAPTOP),
                                  ("MACBOOK", LAPTOP, DESKTOP)):
        page = _as_editor(client).get(f"/partials/queue?machine={machine}")
        assert page.status_code == 200, page.text
        assert mine in page.text, machine
        assert theirs not in page.text, machine


def test_the_home_page_queue_can_be_asked_about_one_computer(dash_env):
    client, conn, _settings = dash_env
    _two_computers(client)

    for machine, mine, theirs in (("IMAC", DESKTOP, LAPTOP),
                                  ("MACBOOK", LAPTOP, DESKTOP)):
        page = _as_editor(client).get(f"/?machine={machine}")
        assert page.status_code == 200, page.text
        # The [ FIX DESTINATION ROOT ] line only: the same page also carries
        # [ PROJECT ROOTS ], which lists every unmapped Resolve project in the
        # fleet on purpose, so a whole-page "not in" would be about that.
        line = page.text.split('class="mono-sm root-line"', 1)[1].split("</div>", 1)[0]
        assert mine in line, machine
        assert theirs not in line, machine
        # ...and the 10s poll has to keep asking about the same computer, or
        # the panel becomes about the other one ten seconds after it is read.
        assert f"machine={machine}" in page.text


def test_an_unknown_computer_is_not_taken_as_a_machine(dash_env):
    """A ?machine= that is not one of this person's computers is the PERSON's
    view, never an empty one: a typo (or a stale bookmark after a rename)
    must not read as "nothing is ticked on that computer"."""
    client, conn, _settings = dash_env
    _two_computers(client)
    person = api_mod.build_queue_view(conn, "jsmith")["resolve_project"]
    page = _as_editor(client).get("/partials/queue?machine=NOT-A-COMPUTER")
    assert page.status_code == 200, page.text
    assert person in page.text


# ------------------------------------------ dash-collector-alerts (the template)

def test_a_preview_that_could_not_count_says_so_instead_of_zero(dash_env, monkeypatch):
    """The refusal's own sentence, not "0 file(s) missing from the server
    now, 0 that are there but different, 0 the same" - which is what a folder
    this server cannot walk rendered as, and which reads as "nothing is
    missing" to the person deciding whether to restore."""
    client, _conn, _settings = dash_env
    from ccsync_dashboard import recovery as recovery_mod

    note = ("That project folder holds more than 200000 files, more than this "
            "server compares in one go, so it cannot say what is missing "
            "without guessing.")
    # The real refusal, as recovery.preview_restore builds it (recovery.py
    # ~320): every count zero, `truncated` and `counts_unavailable` true.
    monkeypatch.setattr(recovery_mod, "preview_restore", lambda *a, **kw: {
        "slug": "ff5", "label": "FF5", "snapshot": "auto-2026-09-11",
        "live_exists": True, "missing": [], "missing_count": 0,
        "missing_bytes": 0, "changed": [], "changed_count": 0,
        "changed_bytes": 0, "unchanged_count": 0, "added": [], "added_count": 0,
        "truncated": True, "counts_unavailable": True, "note": note})
    # The preview block only renders when this site HAS snapshots to offer;
    # everything else about the view stays real.
    real_page_view = recovery_mod.page_view

    def with_snapshots(settings, conn, problem):
        view = real_page_view(settings, conn, problem)
        view["snapshots"] = [{"name": "auto-2026-09-11"}]
        view["projects"] = [{"slug": "ff5", "label": "FF5"}]
        return view

    monkeypatch.setattr(recovery_mod, "page_view", with_snapshots)
    page = _admin(client).post("/partials/admin/recovery/preview",
                               data={"slug": "ff5", "snapshot": "auto-2026-09-11"})
    assert page.status_code == 200, page.text
    assert note in page.text
    assert "missing from the server now" not in page.text


# ------------------------------------------------------- dash-db-5 (the template)

def test_an_unreadable_archived_list_says_so(dash_env, monkeypatch):
    """dash-db-5 separated the archived read so a table this database cannot
    answer for stops taking the whole page down. What was left was an EMPTY
    list, which on this page reads as "nothing is archived"."""
    client, _conn, _settings = dash_env
    from ccsync_dashboard import db as db_in_use

    def unreadable(conn):
        raise sqlite3.OperationalError("no such table: archived_projects")

    monkeypatch.setattr(db_in_use, "fetch_archived_projects", unreadable)
    page = _admin(client).get("/admin/assignments")
    assert page.status_code == 200, page.text
    assert "could not be read" in page.text


# --------------------------------------------------------------------- broll-5

def test_a_locked_client_ledger_does_not_degrade_the_whole_broll_mount(
        tmp_path, monkeypatch):
    """broll-5 gave client_folders an `ensure_schema_best_effort`; the mount
    still called the bare one, so a ledger locked for the seconds the
    container starts hid the archive's search page behind "every /broll
    request will fail until the data root is writable" - about an app that
    was serving every request fine."""
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "brolldata"))
    monkeypatch.setenv("BROLL_INGEST_TOKEN", INGEST)
    modules = _build_fake_broll(tmp_path)

    client_folders = types.ModuleType("app.client_folders")

    def ensure_schema(path=None):
        raise sqlite3.OperationalError("database is locked")

    calls = []

    def ensure_schema_best_effort(path=None):
        calls.append(True)
        try:
            ensure_schema(path)
        except sqlite3.OperationalError:
            return False
        return True

    client_folders.ensure_schema = ensure_schema
    client_folders.ensure_schema_best_effort = ensure_schema_best_effort
    modules["app"].client_folders = client_folders
    modules["app.client_folders"] = client_folders

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=SHARED, broll_enabled=True,
                        broll_ingest_token=INGEST,
                        admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app):
        assert calls, "the mount still called the bare ensure_schema"
        assert app.state.broll_status == "mounted", app.state.broll_status


# --------------------------------------------------------------- regression-11

def test_the_jobs_page_names_the_ffmpeg_sidecar_cause(dash_env):
    """comp-ytdl-jobs-3's companion half stores WHY a machine has no ffmpeg;
    nothing on the dashboard read it, so Settings -> JOBS said only that this
    computer cannot run the job - which reads as "it was never set up"."""
    client, conn, _settings = dash_env
    # IDLE and willing, so the capability refusal is the one that fires:
    # a machine refused for being in use never reaches the ffmpeg question.
    _report(client, machine="EDIT-PC",
            capabilities={"ffmpeg": False, "ffprobe": False, "cpu_count": 8,
                          "idle_seconds": 3600, "jobs_enabled": True,
                          "mounts": ["media", "vault"]},
            sync_guard={
                "ytdlp": {"ok": False, "sidecar": {
                    "ok": False, "action": "failed", "consecutive_failures": 3,
                    "cause": "the download could not verify its certificate",
                    "checked_at": dbmod.utcnow_iso()}},
            })
    job_id = dbmod.create_job(conn, "proxy-480p",
                              {"root": "media", "rel_path": "a.mp4",
                               "out_root": "vault", "out_rel": "cache"},
                              # What a proxy job asks of a machine, as
                              # tools/jobs.py queues it: ffmpeg is the one
                              # this computer has lost.
                              {"ffmpeg": True, "ffprobe": True})
    conn.commit()
    page = _admin(client).get("/partials/admin/jobs")
    assert page.status_code == 200, page.text
    assert str(job_id) in page.text
    # The sentence (jobs.explain builds it) AND the chip that makes it
    # scannable: "this tool's installer failed" and "this computer was never
    # set up" are the same empty answer without one of them.
    assert "could not verify its certificate" in page.text
    assert "[ SIDECAR FAILED ]" in page.text


# ------------------------------------------------- CR-259c's second half (b-1)
# `mount_status.recheck` probes EXISTENCE now (dash-collector-alerts did that
# half), so music and ytdl can finally name a witness that goes away with their
# export. Until they did, both recorded the bind MOUNTPOINT - a directory that
# is still there after the export behind it is gone - and the collector's
# per-cycle re-probe answered "mounted" in every failure it was written for.

def test_the_music_mount_notices_its_export_going_away(music_env, tmp_path):
    from ccsync_dashboard import mount_status

    assert mount_status.snapshot()["music"][0] == "mounted"
    # The export goes: the bind MOUNTPOINT stays behind (this is the mechanism
    # - the directory is still a directory), the database does not.
    (tmp_path / "musicdata" / "music.db").unlink()
    changed = mount_status.recheck()
    assert changed.get("music", ("",))[0] == "degraded", changed
    # ...and the sentence names the ROOT, not the file this server stat'ed.
    assert str(tmp_path / "musicdata") in changed["music"][1]


def test_the_ytdl_mount_notices_its_export_going_away(ytdl_env, tmp_path):
    from ccsync_dashboard import mount_status

    assert mount_status.snapshot()["ytdl"][0] == "mounted"
    (tmp_path / "ytdldata" / "ytdl.db").unlink()
    changed = mount_status.recheck()
    assert changed.get("ytdl", ("",))[0] == "degraded", changed
