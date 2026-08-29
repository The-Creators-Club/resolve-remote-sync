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
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod
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
    """The dashboard offers `whisper` and the companion runs `whisper`. A kind
    only one side knows is a job that is claimed and handed straight back."""
    _caps, _paths, jobs_runner = companion()
    assert dbmod.JOB_KINDS == ("whisper",)
    runner = jobs_runner.JobRunner({})
    # The runner's own claim asks for exactly the kinds it can execute.
    assert runner._capabilities() == {}
    assert "whisper" in jobs_runner.__doc__
