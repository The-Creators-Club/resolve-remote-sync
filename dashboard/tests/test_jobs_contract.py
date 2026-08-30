"""The wire between the companion and the dashboard, for fleet jobs.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 0 (2026-08-29). The two halves are
separate deployment units on separate release cadences: the companion is a
frozen exe on somebody's PC and the dashboard is a container on the NAS. Every
disagreement between them is therefore discovered in the field, on a machine
nobody is sitting at -- which is exactly the class of bug this file exists to
catch at CI time instead.

Pinned here, the way test_packages.py pins the release record's two
implementations:

  * the report reply's `commands.jobs` shape, as the dashboard writes it and
    the companion's `note_report_reply` reads it;
  * the three fleet routes' paths and bodies, as the companion builds them and
    the dashboard's routes accept them;
  * the `capabilities` section, as the companion builds it and the dashboard's
    model parses it -- including that a null idle answer survives the trip;
  * the (root, rel_path) discipline: the dashboard never sends a path, and the
    companion refuses one that is not relative.

Phase 2 (2026-08-30) adds the second wire between the same two units: the
Timeline Cards agent tunnel. The companion's role builds the URL, the method,
the credential and the body; the real app answers them. It is the same class
of bug and the same cost -- a renamed suffix here is a machine that quietly
stops driving Resolve while both halves look healthy.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, jobs as jobs_mod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"


def companion():
    """The companion package, or a skip when there is no checkout beside us
    (the ed25519 pair's rule, same reasoning)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                           / "companion" / "src"))
    try:
        from ccsync_companion import capabilities, job_paths, jobs_runner
    except ImportError:                                       # pragma: no cover
        pytest.skip("no companion checkout beside this one")
    return capabilities, job_paths, jobs_runner


def cards_role():
    """The companion's Timeline Cards role, or a skip. Same rule as above."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                           / "companion" / "src"))
    try:
        from ccsync_companion import timeline_cards_role
    except ImportError:                                       # pragma: no cover
        pytest.skip("no companion checkout beside this one")
    return timeline_cards_role


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "contract.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def as_admin(client):
    """The session cookie an admin submits with. DASH_DEV_INSECURE (set by
    conftest at import time) is what relaxes the CSRF token here; the real
    non-browser path is `POST /api/v1/login`'s `csrf`, pinned in
    test_jobs.py."""
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def hdr(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def test_the_offer_block_the_dashboard_writes_is_the_one_the_runner_reads(env):
    _caps, _paths, jobs_runner = companion()
    client, conn = env
    job_id = dbmod.create_job(conn, "whisper", {"root": "vault", "rel_path": "V/x"})
    conn.commit()
    reply = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
        "capabilities": {"whisper": True, "idle_seconds": 900, "mounts": ["vault"]},
    }, headers=hdr()).json()

    runner = jobs_runner.JobRunner({}, machine_name="EDIT-PC")
    runner.note_report_reply(reply)
    assert runner.status()["offered"] == [job_id]


def test_the_capabilities_section_the_companion_builds_parses_here(env, tmp_path):
    caps_mod, _paths, _runner = companion()
    client, conn = env
    section = caps_mod.build({"local_root": str(tmp_path)}, use_cache=False)
    r = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(), "capabilities": section,
    }, headers=hdr())
    assert r.status_code == 200, r.text
    stored = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert stored != {}, "the section the companion sends must be storable"
    # None means cannot tell means not idle, all the way through: no probe
    # here, so the section carries null and the column keeps it.
    assert section["idle_seconds"] is None
    assert stored["idle_seconds"] is None
    # EVERY key the companion builds has to survive the trip. A field the
    # report model does not declare is dropped SILENTLY by pydantic, which is
    # how `ffprobe` reached the dashboard as False on its first run here and
    # made every machine look incapable of the three media kinds.
    scalars = {k: v for k, v in section.items()
               if not isinstance(v, (dict, list)) and k in stored}
    assert scalars, "the section and the stored row share no fields at all"
    for key, value in scalars.items():
        assert stored[key] == value, f"{key} did not survive the report"
    assert "ffprobe" in stored


def test_the_runner_calls_the_routes_this_dashboard_serves(env, tmp_path):
    """The companion builds the URL and the body; the real app answers them.

    This is the test that would have caught a renamed route or a renamed
    field -- the failure that otherwise shows up as a machine that quietly
    never claims anything.
    """
    _caps, _paths, jobs_runner = companion()
    client, conn = env
    job_id = dbmod.create_job(conn, "whisper",
                              {"root": "vault", "rel_path": "V/x"}, {"whisper": True})
    dbmod.upsert_machine_state(conn, "jsmith", "EDIT-PC", None, dbmod.utcnow_iso())
    conn.commit()

    def request(method, url, body, headers, timeout):
        path = url.replace("http://dash.example", "")
        resp = client.request(method, path, json=body, headers=headers)
        try:
            return resp.status_code, resp.json()
        except ValueError:                                    # pragma: no cover
            return resp.status_code, None

    runner = jobs_runner.JobRunner(
        {"dashboard_url": "http://dash.example", "dashboard_token": TOKEN},
        request_fn=request,
        identity_token_fn=lambda: auth.make_identity_token(SECRET, "jsmith"),
        capabilities_fn=lambda: {"whisper": True, "idle_seconds": 900},
        machine_name="EDIT-PC")

    job = runner._claim()
    assert job is not None and job["id"] == job_id
    assert runner._heartbeat(job_id) is True
    runner._post_result(job_id, True, result={"files": ["Clips/a/a_words.json"]})
    assert dbmod.get_job(conn, job_id)["state"] == dbmod.JOB_DONE

    # ...and a heartbeat for a job this machine no longer holds is a 410,
    # which the runner reads as "stop, quietly".
    assert runner._heartbeat(job_id) is False


def test_a_job_carries_roots_and_relative_paths_only(env, tmp_path):
    """§4.1's discipline, checked from both ends: the dashboard stores what it
    is given, and the companion refuses to place anything absolute."""
    _caps, job_paths, _runner = companion()
    client, conn = env
    vault = tmp_path / "vault"
    (vault / "Vault" / "2026").mkdir(parents=True)
    cfg = {"local_root": str(tmp_path), "jobs_vault_root": str(vault)}
    inputs = {"root": "vault", "rel_path": "Vault/2026"}
    job_id = dbmod.create_job(conn, "whisper", inputs)
    conn.commit()
    stored = dbmod.get_job(conn, job_id)["inputs"]
    placed = job_paths.resolve(cfg, stored["root"], stored["rel_path"])
    assert placed == (vault / "Vault" / "2026").resolve()
    with pytest.raises(job_paths.JobPathError):
        job_paths.resolve(cfg, "vault", str(vault / "Vault"))


def test_the_kinds_the_two_sides_know_do_not_drift():
    """Every kind the dashboard offers is one this companion can run.

    A kind only the DASHBOARD knows is a job that is claimed and handed
    straight back; one only the COMPANION knows is a runner nothing will ever
    reach. Asked of a machine with every capability, so the answer is about
    the code and not about this laptop.
    """
    _caps, _paths, jobs_runner = companion()
    runner = jobs_runner.JobRunner(
        {}, capabilities_fn=lambda: {"whisper": True, "ffmpeg": True,
                                     "ffprobe": True})
    assert sorted(runner.runnable_kinds()) == sorted(dbmod.JOB_KINDS)
    # ...and a machine that has reported nothing asks for nothing, rather
    # than for everything.
    assert jobs_runner.JobRunner({}).runnable_kinds() == []


def test_a_media_job_goes_out_and_comes_back_whole(env, tmp_path):
    """The phase-1 wire, end to end with no ffmpeg: the dashboard fills in the
    requirements, the machine matches them, the runner places both roots, and
    the result's file paths are relative to the root they were written under.

    This is the test that would catch a renamed input key -- the failure that
    otherwise shows up as a lane spinning for ever while a job sits `queued`.
    """
    _caps, job_paths, jobs_runner = companion()
    client, conn = env
    media = tmp_path / "media"
    vault = tmp_path / "vault"
    (media / "FF5").mkdir(parents=True)
    (media / "FF5" / "Interview.mp4").write_bytes(b"not really an mp4")
    out_rel = "Vault/2026/FF5/Ep/Script Docs/remote_audio/source"
    (vault / out_rel).mkdir(parents=True)
    dbmod.upsert_machine_state(conn, "jsmith", "EDIT-PC", None, dbmod.utcnow_iso())
    conn.commit()

    def request(method, url, body, headers, timeout):
        resp = client.request(method, url.replace("http://dash.example", ""),
                              json=body, headers=headers)
        return resp.status_code, resp.json()

    # The dashboard's own submit route, with NO requires: the standard set is
    # the dashboard's to fill in, and it names both roots.
    submitted = as_admin(client).post("/api/v1/jobs", json={
        "kind": "proxy-480p",
        "inputs": {"root": "media", "rel_path": "FF5/Interview.mp4",
                   "out_root": "vault", "out_rel": out_rel},
    })
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()["job"]
    assert job["requires"] == {"ffmpeg": True, "ffprobe": True,
                               "mount": ["media", "vault"]}

    cfg = {"dashboard_url": "http://dash.example", "dashboard_token": TOKEN,
           "local_root": str(tmp_path), "jobs_vault_root": str(vault),
           "jobs_media_root": str(media)}
    runner = jobs_runner.JobRunner(
        cfg, request_fn=request,
        identity_token_fn=lambda: auth.make_identity_token(SECRET, "jsmith"),
        capabilities_fn=lambda: {"ffmpeg": True, "ffprobe": True,
                                 "mounts": ["tree", "vault", "media"],
                                 "idle_seconds": 900},
        machine_name="EDIT-PC")
    claimed = runner._claim()
    assert claimed is not None and claimed["id"] == job["id"]

    source, out_dir, stem, out_root, placed_rel = runner._media_paths(claimed)
    assert source == (media / "FF5" / "Interview.mp4").resolve()
    assert out_dir == (vault / out_rel).resolve()
    assert (stem, out_root, placed_rel) == ("Interview", "vault", out_rel)

    # A heartbeat carrying a fraction, and the grid's chip reading it back.
    assert runner._heartbeat(job["id"], 0.62) is True
    chip = dbmod.fetch_running_jobs_map(conn)[("jsmith", "EDIT-PC")]
    assert (chip["label"], chip["percent"]) == ("PROXY 480p", 62)

    runner._post_result(job["id"], True, result={
        "files": [f"{out_rel}/Interview.480p.mp4"], "out_root": "vault",
        "seconds": 3.3, "realtime": 11.0})
    stored = dbmod.get_job(conn, job["id"])
    assert stored["state"] == dbmod.JOB_DONE
    # Relative, and named with the root it is relative TO.
    assert stored["result"]["out_root"] == "vault"
    assert not stored["result"]["files"][0].startswith(str(vault))


# ------------------------------------------------- the cards agent tunnel

def test_the_role_calls_the_tunnel_routes_this_dashboard_serves(tmp_path, monkeypatch):
    """The companion builds the three calls; the real app routes them.

    The upstream cards server is a stub here -- what is being pinned is the
    seam BETWEEN the two deployment units, not the third one. A renamed
    suffix, a lost header or a `wait` that stopped being forwarded all show up
    here instead of as a page that stopped updating.
    """
    role_mod = cards_role()
    from ccsync_dashboard import cards_tunnel

    sent = []

    class Upstream:
        def open(self, request, timeout=None):
            sent.append((request.get_method(), request.full_url,
                         dict(request.headers), timeout))

            class R:
                def read(self_inner):
                    return b'{"ok": true, "version": 5}'

                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc):
                    return False
            return R()

    monkeypatch.setattr(cards_tunnel, "_opener", Upstream)
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "tunnel.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects),
                        cards_server_url="http://cards.invalid:8800",
                        cards_token="cards-token-not-a-real-one")
    with TestClient(create_app(settings)) as client:
        def request(method, url, body, headers, timeout):
            # The role hands us an absolute URL against the dashboard; the
            # test client wants the path.
            path = url.split("/", 3)[-1]
            resp = client.request(method, "/" + path, json=body, headers=headers)
            return resp.status_code, (resp.json() if resp.content else None)

        role = role_mod.TimelineCardsRole(
            {"cards_agent": True, "dashboard_url": "http://dash.example",
             "dashboard_token": TOKEN,
             "jobs_mulcam_pipeline": str(tmp_path), "jobs_vault_root": str(tmp_path)},
            request_fn=request,
            identity_token_fn=lambda: auth.make_identity_token(SECRET, "jsmith"),
            processes_fn=lambda: [])

        assert role.call("/agent/state", {"token": "", "name": "EDIT-PC",
                                          "state": {"timeline": "E1"}})             == {"ok": True, "version": 5}
        assert role.call("/agent/pending?wait=25&token=") == {"ok": True,
                                                              "version": 5}
        assert role.call("/agent/result", {"id": 1, "ok": True}) == {
            "ok": True, "version": 5}

    methods = [call[0] for call in sent]
    urls = [call[1] for call in sent]
    assert methods == ["POST", "GET", "POST"]
    assert urls[0].endswith("/agent/state")
    assert urls[1].endswith("/agent/pending?wait=25")
    assert urls[2].endswith("/agent/result")
    # The dashboard attached its own token; the companion never held one.
    for _method, _url, headers, _timeout in sent:
        assert headers.get("X-cards-token") == "cards-token-not-a-real-one"


def test_the_cards_report_block_the_role_builds_parses_here(env, tmp_path):
    """capabilities.cards_agent, built by the role and stored by the schema.

    The `ffprobe` lesson (phase 1): a field the report model does not declare
    is dropped SILENTLY by pydantic, and the symptom is a fleet grid that is
    simply missing a chip nobody can explain.
    """
    role_mod = cards_role()
    caps_mod, _paths, _runner = companion()
    client, conn = env
    role = role_mod.TimelineCardsRole({"cards_agent": False},
                                      processes_fn=lambda: [])
    section = caps_mod.build({"local_root": str(tmp_path)}, use_cache=False,
                             cards_agent_fn=role.report_block)
    assert set(section["cards_agent"]) == {"connected", "state", "timeline",
                                           "version", "since"}
    r = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(), "capabilities": section,
    }, headers=hdr())
    assert r.status_code == 200, r.text
    stored = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["cards_agent"]
    for key, value in section["cards_agent"].items():
        if value is None:
            continue
        assert stored[key] == value, f"cards_agent.{key} did not survive the report"


# ---------------------------------------------------- phase 4 (2026-08-30)
#
# Three more fields on the same two wires, and each of them is a bug that
# would only show up in the field if the two halves disagreed: a cancel that
# never reaches the machine running the job, a depth signal a companion reads
# as zero and backs off on for ever, and an allow-list that silently takes
# every machine out of the queue.


def test_the_cancel_the_dashboard_sends_is_the_one_the_runner_reads(env):
    _caps, _paths, jobs_runner = companion()
    client, conn = env
    job_id = dbmod.create_job(conn, "peaks", {"root": "media", "rel_path": "a.mp4"})
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    as_admin(client).post(f"/api/v1/jobs/{job_id}/cancel")

    reply = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
    }, headers=hdr()).json()
    runner = jobs_runner.JobRunner({}, machine_name="EDIT-PC")
    runner.note_report_reply(reply)
    assert runner._cancel_requested(job_id) is True


def test_the_depth_signal_the_dashboard_sends_is_the_one_the_runner_backs_off_on(env):
    _caps, _paths, jobs_runner = companion()
    client, conn = env
    reply = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
    }, headers=hdr()).json()
    runner = jobs_runner.JobRunner({"jobs_poll_seconds": 20},
                                   machine_name="EDIT-PC")
    runner.note_report_reply(reply)
    # An empty fleet queue sends no block at all, and the runner keeps its
    # cadence: no key means "an older dashboard", which must not be read as
    # "nothing to do for ever".
    assert runner.wait_seconds() == 20.0

    dbmod.create_job(conn, "peaks", {"root": "media", "rel_path": "a.mp4"})
    conn.commit()
    reply = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
    }, headers=hdr()).json()
    runner.note_report_reply(reply)
    assert runner.status()["queue"]["queued"] == 1
    assert set(runner.status()["queue"]) == {"queued", "running", "pinned",
                                             "oldest_age_s"}


def test_the_allow_list_the_companion_reports_is_the_one_the_scheduler_filters_on(
        env, tmp_path):
    """The `ffprobe` lesson again: a field the report model does not declare
    is dropped SILENTLY, and the symptom here would be a laptop being handed
    exactly the work its owner excluded."""
    caps_mod, _paths, _runner = companion()
    client, conn = env
    section = caps_mod.build({"local_root": str(tmp_path),
                              "jobs_kinds": ["proxy-480p"]},
                             use_cache=False)
    assert section["job_kinds"] == ["proxy-480p"]
    r = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(), "capabilities": section,
    }, headers=hdr())
    assert r.status_code == 200, r.text
    stored = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert stored["job_kinds"] == ["proxy-480p"]
    assert dbmod.machine_allows_kind(stored, "proxy-480p") is True
    assert dbmod.machine_allows_kind(stored, "whisper") is False


def test_an_empty_allow_list_survives_as_every_kind(env, tmp_path):
    caps_mod, _paths, _runner = companion()
    client, conn = env
    section = caps_mod.build({"local_root": str(tmp_path)}, use_cache=False)
    assert section["job_kinds"] == []
    client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(), "capabilities": section,
    }, headers=hdr())
    stored = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert stored["job_kinds"] == []
    assert dbmod.machine_allows_kind(stored, "whisper") is True


# ------------------- section 10: force, target and volunteer, on the wire
#
# The companion half of this (0.9.61) is built in its own worktree at the same
# time, so these pin the DASHBOARD's side of section 10.2's contract exactly
# as it is written down: the key names, the types, and which of them are
# present when they have nothing to say. Every one of them is a field 0.7.22
# neither sends nor stores, which is what makes the two halves deployable in
# either order (section 9.3's rule).


def test_the_reply_names_the_forced_jobs_as_a_subset_of_the_offered_ones(env):
    """`commands.jobs.forced` is how a companion with somebody at the keyboard
    learns that this particular job was meant to interrupt them. A build older
    than 0.9.61 ignores the key and claims on its own gate as before."""
    client, conn = env
    ordinary = dbmod.create_job(conn, "whisper", {"root": "vault", "rel_path": "V/a"})
    forced = dbmod.create_job(conn, "whisper", {"root": "vault", "rel_path": "V/b"},
                              forced=True)
    conn.commit()
    reply = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
        "capabilities": {"whisper": True, "idle_seconds": 900, "mounts": ["vault"]},
    }, headers=hdr()).json()
    block = reply["commands"]["jobs"]
    assert block["forced"] == [forced]
    assert set(block["offered"]) == {ordinary, forced}


def test_the_forced_key_is_absent_when_there_is_nothing_to_force(env):
    """The broll_ingest rule: an empty list is not an instruction, and this
    block rides every tick of every machine in the fleet."""
    client, conn = env
    dbmod.create_job(conn, "whisper", {"root": "vault", "rel_path": "V/a"})
    conn.commit()
    reply = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
        "capabilities": {"whisper": True, "idle_seconds": 900, "mounts": ["vault"]},
    }, headers=hdr()).json()
    assert "forced" not in reply["commands"]["jobs"]
    assert reply["commands"]["jobs"]["offered"]


def test_a_volunteer_deadline_survives_the_report(env):
    """`volunteer_until` is an ISO-8601 UTC string or null, in EVERY
    capabilities section from 0.9.61. Absent from an older build, which reads
    as null -- never as "volunteering"."""
    client, conn = env
    until = (dbmod.parse_iso(dbmod.utcnow_iso())
             + dt.timedelta(minutes=30)).isoformat()
    client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
        "capabilities": {"ffmpeg": True, "idle_seconds": 0,
                         "volunteer_until": until},
    }, headers=hdr())
    stored = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert stored["volunteer_until"] == until
    assert jobs_mod.is_volunteering(stored) is True


def test_an_unparseable_volunteer_deadline_does_not_422_the_whole_report(env):
    """It is a STRING on the model on purpose: the one thing done with it is
    a comparison against now, and throwing away the whole report of a machine
    that is otherwise fine, over a timestamp, is the wrong trade."""
    client, conn = env
    r = client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
        "capabilities": {"ffmpeg": True, "idle_seconds": 0,
                         "volunteer_until": "half past four"},
    }, headers=hdr())
    assert r.status_code == 200, r.text
    stored = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert jobs_mod.is_volunteering(stored) is False


def test_a_claim_may_name_the_ids_it_wants(env):
    """A companion whose own gate is shut but which holds forced offers
    claims with `ids = forced`, and gets that job and no other."""
    client, conn = env
    ordinary = dbmod.create_job(conn, "peaks", {"root": "vault", "rel_path": "V/a"})
    forced = dbmod.create_job(conn, "peaks", {"root": "vault", "rel_path": "V/b"},
                              forced=True)
    dbmod.upsert_machine_state(conn, "jsmith", "EDIT-PC", None, dbmod.utcnow_iso())
    conn.commit()
    caps = {"ffmpeg": True, "ffprobe": True, "mounts": ["vault"],
            "idle_seconds": 900}
    answer = client.post("/api/v1/jobs/claim",
                         json={"machine": "EDIT-PC", "capabilities": caps,
                               "ids": [forced]},
                         headers=hdr()).json()
    assert answer["job"]["id"] == forced
    assert dbmod.get_job(conn, ordinary)["state"] == dbmod.JOB_QUEUED


def test_a_claim_without_ids_is_the_call_an_older_companion_makes(env):
    """`ids` is optional and null means "anything you offered me" -- 0.9.60's
    body, unchanged, still claims."""
    client, conn = env
    job_id = dbmod.create_job(conn, "peaks", {"root": "vault", "rel_path": "V/a"})
    dbmod.upsert_machine_state(conn, "jsmith", "EDIT-PC", None, dbmod.utcnow_iso())
    conn.commit()
    answer = client.post("/api/v1/jobs/claim", json={
        "machine": "EDIT-PC",
        "capabilities": {"ffmpeg": True, "ffprobe": True, "mounts": ["vault"],
                         "idle_seconds": 900}}, headers=hdr()).json()
    assert answer["job"]["id"] == job_id


def test_submitting_with_the_two_levers_and_reading_them_back(env):
    """`force` and `target_machine` on the body, `forced` and
    `target_machine` on the row -- the names differ on purpose (`forced` is
    the column, so it never argues with SQL) and both halves are pinned
    here."""
    client, _conn = env
    # One machine reporting, under a different name: otherwise the receipt
    # answers "no machine has ever reported here", which is a truer sentence
    # and not the one this test is about.
    client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "OTHER-PC", "lanes": [],
        "reported_at": dbmod.utcnow_iso(),
        "capabilities": {"ffmpeg": True, "ffprobe": True, "mounts": ["vault"],
                         "idle_seconds": 900}}, headers=hdr())
    r = as_admin(client).post("/api/v1/jobs", json={
        "kind": "peaks", "inputs": {"root": "vault", "rel_path": "V/a",
                                    "out_root": "vault", "out_rel": "V/cache"},
        "force": True, "target_machine": "EDIT-PC"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job"]["forced"] is True
    assert body["job"]["target_machine"] == "EDIT-PC"
    # ...and the receipt's why carries them too, so a submitter who typed a
    # machine name that nobody answers to learns it at submit time.
    assert body["why"]["reason_code"] == jobs_mod.REASON_TARGET_UNKNOWN
    again = client.get(f"/api/v1/jobs/{body['job']['id']}").json()["job"]
    assert (again["forced"], again["target_machine"]) == (True, "EDIT-PC")


def test_a_job_submitted_without_the_levers_is_the_body_0_7_22_sent(env):
    """Both fields default, so every existing submitter keeps working and no
    job silently becomes forced."""
    client, _conn = env
    body = as_admin(client).post("/api/v1/jobs", json={
        "kind": "peaks", "inputs": {"root": "vault", "rel_path": "V/a",
                                    "out_root": "vault", "out_rel": "V/cache"},
    }).json()
    assert body["job"]["forced"] is False
    assert body["job"]["target_machine"] == ""
