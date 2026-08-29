"""The `capabilities` report section, its columns, and what the scheduler
does with them (TIMELINE-CARDS-INTO-CCSYNC.md §4.3, phase 0).

The rule every test here defends is B6's, one more time: a diagnostic section
is never worth a 422, and a machine that sends a malformed, oversize or
future-shaped section stays on the fleet grid with its lanes intact. The rule
specific to THIS section is idle.py's: null is not zero, and a machine that
cannot say how idle it is counts as busy.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api, auth, db as dbmod, jobs as jobs_mod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"

CAPS = {
    "gpu_present": True, "gpu_name": "NVIDIA GeForce RTX 3080", "gpu_vram_gb": 10.0,
    "nvenc": True, "ffmpeg": True, "whisper": True, "whisper_detail": "",
    "claude": False, "mounts": ["tree", "vault"], "cpu_count": 16,
    "idle_seconds": 900.0, "load": None, "jobs_enabled": True,
    "resolve": {"running": False, "project": "FF5 Animals"},
}


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "caps.db"), session_secret=SECRET,
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


def report(client, **sections):
    body = {"editor_name": "jsmith", "machine": "EDIT-PC",
            "companion_version": "0.9.56",
            "reported_at": "2026-08-29T10:00:00+00:00", "lanes": []}
    body.update(sections)
    return client.post("/api/v1/report", json=body, headers=hdr())


def test_the_columns_land(env):
    client, conn = env
    assert report(client, capabilities=CAPS).status_code == 200
    caps = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert caps["gpu_present"] is True
    assert caps["gpu_vram_gb"] == 10.0
    assert caps["whisper"] is True
    assert caps["mounts"] == ["tree", "vault"]
    assert caps["idle_seconds"] == 900.0
    assert caps["resolve"]["project"] == "FF5 Animals"


def test_no_section_means_unknown_not_empty(env):
    client, conn = env
    assert report(client).status_code == 200
    assert dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC") == {}


def test_a_second_report_without_the_section_keeps_the_answer(env):
    """Absent is not empty: a companion mid-restart must not blank hardware."""
    client, conn = env
    report(client, capabilities=CAPS)
    report(client)
    assert dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["whisper"] is True


def test_the_section_is_replaced_wholesale(env):
    """A vault that is no longer mounted has to be able to STOP being a mount,
    or a job is claimed by the one machine that cannot read it."""
    client, conn = env
    report(client, capabilities=CAPS)
    report(client, capabilities=dict(CAPS, mounts=["tree"], whisper=False))
    caps = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert caps["mounts"] == ["tree"]
    assert caps["whisper"] is False


def test_null_idle_is_stored_as_null_and_not_zero(env):
    client, conn = env
    report(client, capabilities=dict(CAPS, idle_seconds=None))
    assert dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["idle_seconds"] is None


def test_a_malformed_section_is_dropped_not_422(env):
    client, conn = env
    r = report(client, capabilities={"gpu_vram_gb": "a lot", "mounts": "vault"})
    assert r.status_code == 200, r.text
    assert dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC") == {}


def test_an_unknown_field_does_not_refuse_the_report(env):
    client, conn = env
    r = report(client, capabilities=dict(CAPS, some_future_thing={"a": 1}))
    assert r.status_code == 200
    assert dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["gpu_present"] is True


def test_a_reported_machine_is_offered_a_job_it_can_do(env):
    """The end-to-end contract of phase 0: a capability arrives on a report,
    and the reply to that same report offers the work."""
    client, conn = env
    job_id = dbmod.create_job(conn, "whisper",
                              {"root": "vault", "rel_path": "Vault/2026/x"},
                              {"whisper": True, "gpu_vram_gb": 6, "mount": "vault"})
    conn.commit()
    r = report(client, capabilities=CAPS)
    assert r.json()["commands"]["jobs"] == {"offered": [job_id]}


def test_a_machine_with_somebody_at_it_is_offered_nothing(env):
    client, conn = env
    dbmod.create_job(conn, "whisper", {"root": "vault", "rel_path": "Vault/2026/x"},
                     {"whisper": True})
    conn.commit()
    r = report(client, capabilities=dict(CAPS, idle_seconds=5))
    assert "jobs" not in r.json()["commands"]


def test_the_grid_carries_the_chips(env):
    """The chips are rendered from build_editors_view, so this is the seam
    that decides whether [ GPU 10G ] and [ WHISPER ] can exist at all."""
    client, conn = env
    report(client, capabilities=CAPS)
    entry = next(e for e in api.build_editors_view(conn)["editors"]
                 if e["machine"] == "EDIT-PC")
    assert entry["capabilities"]["gpu_present"] is True
    assert entry["capabilities"]["whisper"] is True
    assert entry["capabilities"]["gpu_vram_gb"] == 10.0


def test_a_running_job_is_on_the_grid(env):
    client, conn = env
    report(client, capabilities=CAPS)
    job_id = dbmod.create_job(conn, "whisper", {"root": "vault", "rel_path": "V/x"})
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    entry = next(e for e in api.build_editors_view(conn)["editors"]
                 if e["machine"] == "EDIT-PC")
    assert entry["job"]["id"] == job_id
    assert entry["job"]["kind"] == "whisper"
