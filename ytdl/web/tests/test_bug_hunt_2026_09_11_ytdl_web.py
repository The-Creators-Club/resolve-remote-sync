"""Regression tests for the 2026-09-11 hunt's ytdl-web findings (CR-244).

One section per finding id, so `grep -rn ytdl-web-3 tests/` lands on the test
that pins it as well as on the code that fixes it.
"""
import pytest

from tests.conftest import PROJECTS, USER
from tests.test_local_download import (  # noqa: F401  (fleet is a fixture)
    FRESH_YTDLP, _claim_body, _expire_lease, _identity_header, fleet,
    SECRET, TOKEN)
from ytdlweb import config, db, routes_api


DESKTOP = 'm-desktop-0001'
LAPTOP = 'm-laptop-0002'


def _downloading_job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb'), **over):
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label, **over)
    for vid in ids:
        db.add_video(con, job_id, vid, f'https://www.youtube.com/watch?v={vid}',
                     f'{vid} title')
    con.commit()
    db.mark_pending(con, job_id)
    db.set_job(con, job_id, dl_total=len(ids))
    db.set_phase(con, job_id, 'downloading')
    return db.get_job(con, job_id)


def _ready_job(con, seconds=3600):
    """A job at ready_for_review with one sizeable clip selected: what the
    DOWNLOAD press is dispatched from."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label)
    db.add_video(con, job_id, 'aaaaaaaaaaa', 'u')
    db.set_video(con, job_id, 'aaaaaaaaaaa', duration=seconds)
    db.set_phase(con, job_id, 'ready_for_review')
    return db.get_job(con, job_id)


# ---------------------------------------------------------------- ytdl-web-1

def test_a_vanished_projects_mount_is_its_own_refusal_and_not_disk_full(
        client, con, tmp_path, monkeypatch):
    """The bind mount goes away and leaves its mount point behind, so
    disk_usage answers for the CONTAINER's own overlay filesystem. Refusing
    with "there is only 2 GB free, delete something" sends the editor to
    delete footage for a reason that is not true, and the second press says
    the same thing."""
    routes_api._free_cache.clear()
    empty_root = tmp_path / 'projects'          # the leftover mount point
    empty_root.mkdir()
    monkeypatch.setattr(config, 'PROJECTS_ROOT', empty_root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 2 * 10 ** 9})())
    job = _ready_job(con)

    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409, r.json()
    detail = r.json()['detail']
    assert detail['reason'] == 'tree_missing', detail
    assert 'Free some space' not in detail['detail'], detail
    assert str(empty_root) in detail['detail'], detail
    # ...and nothing was started, exactly as the disk gate leaves it.
    assert db.get_job(con, job['id'])['phase'] == 'ready_for_review'


def test_a_real_tree_still_refuses_a_full_disk(client, con, tmp_path,
                                               monkeypatch):
    """The mount-is-gone guard must not become a way for the disk gate to
    stop working: with the project folder there, the number is the tree's."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    (root / PROJECTS[0][1]).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 2 * 10 ** 9})())
    job = _ready_job(con)

    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409, r.json()
    assert r.json()['detail']['reason'] == 'disk_full'


# ---------------------------------------------------------------- ytdl-web-2

def test_the_second_press_after_freeing_space_is_measured_fresh(
        client, con, tmp_path, monkeypatch):
    """"Free some space and press DOWNLOAD again" was the one action the 60 s
    cache invalidated: the second press got a byte-identical 409 quoting the
    pre-deletion number."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    (root / PROJECTS[0][1]).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    free = [2 * 10 ** 9]
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': free[0]})())
    job = _ready_job(con)

    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 409
    free[0] = 900 * 10 ** 9                     # the editor frees 900 GB
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200


# ---------------------------------------------------------------- ytdl-web-6

def test_the_free_space_cache_is_one_entry_per_filesystem():
    """One entry per destination meant one entry per SEARCH, for the life of
    the container. The number being cached belongs to a filesystem."""
    routes_api._free_cache.clear()
    a = config.PROJECTS_ROOT / '2026/FF5/Energy Transition/Youtube/algal reef'
    b = config.PROJECTS_ROOT / '2026/FF5/Water/Youtube/kelp forest'
    assert routes_api.free_bytes_at(a) is not None
    assert routes_api.free_bytes_at(b) is not None
    assert len(routes_api._free_cache) == 1, routes_api._free_cache


# ---------------------------------------------------------------- ytdl-web-4

def test_a_local_download_is_not_refused_by_the_servers_own_disk(
        client, con, tmp_path, monkeypatch):
    """With requester-first downloads on, the clips land on the EDITOR's disk
    and the companion does its own free-space decision at claim time. The
    server measuring the NAS and refusing outright blocks a download that was
    never going to touch the filesystem it measured."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    (root / PROJECTS[0][1]).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 2 * 10 ** 9})())
    job = _ready_job(con)
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200


# ---------------------------------------------------------------- ytdl-web-3

def test_a_heartbeat_from_a_machine_that_is_not_the_holder_is_410(fleet, con):
    """Laptop A stalls past the lease, desktop B claims legitimately, A wakes
    up: per-EDITOR its heartbeat re-extended the lease that now belongs to B,
    and A downloaded all forty clips into a second tree."""
    job = _downloading_job(con)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(machine_id=DESKTOP)).status_code == 200

    r = fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                   json={'editor': USER, 'machine_id': LAPTOP})
    assert r.status_code == 410, r.json()
    # ...and the holder's own heartbeat still works.
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER, 'machine_id': DESKTOP}
                      ).status_code == 200


def test_a_heartbeat_with_no_machine_id_is_the_older_companion(fleet, con):
    """The field is OPTIONAL on the wire: a companion below this build sends
    no machine_id and must keep today's per-editor answer, or every machine in
    the fleet starts getting 410s mid-download."""
    job = _downloading_job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER}).status_code == 200


def test_a_clip_status_from_the_wrong_machine_is_410(fleet, con):
    """The status post is what records download_host and marks the clip done
    for the run the OTHER computer is doing."""
    job = _downloading_job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))
    r = fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
                   json={'state': 'done', 'filepath_rel': 'a.mp4',
                         'machine_id': LAPTOP})
    assert r.status_code == 410, r.json()
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] != 'done'


def test_the_manifest_is_refused_to_the_machine_that_is_not_the_holder(
        fleet, con):
    job = _downloading_job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))
    assert fleet.get(f'/api/jobs/{job["id"]}/download-manifest',
                     params={'machine_id': LAPTOP}).status_code == 410
    assert fleet.get(f'/api/jobs/{job["id"]}/download-manifest',
                     params={'machine_id': DESKTOP}).status_code == 200
    # No machine id at all is the older companion, and unchanged.
    assert fleet.get(f'/api/jobs/{job["id"]}/download-manifest'
                     ).status_code == 200


def test_a_holder_that_did_not_say_which_machine_is_not_evicted(fleet, con):
    """A NULL claimed_machine is "the holder did not say", not "another
    machine" -- refusing it would strand a live lease the moment the companion
    holding it upgraded mid-job."""
    job = _downloading_job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER, 'machine_id': LAPTOP}
                      ).status_code == 200


# ---------------------------------------------------------------- ytdl-web-5

def test_a_job_created_under_the_widening_cannot_be_claimed(fleet, con):
    """CR-96 widens the destination to every active project when the download
    will run on the SERVER. The widening was granted on the promise that no
    machine claims the job, and nothing enforced it: a client could post
    local:false to reach a project it does not sync and then hand the job id
    to its own companion on 127.0.0.1:8899."""
    job = _downloading_job(con, created_local=False)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim',
                   json=_claim_body(machine_id=DESKTOP))
    assert r.status_code == 410, r.json()
    assert r.json()['detail']['reason'] == 'created_widened'
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


def test_the_claim_door_is_the_one_that_refuses_it(con):
    """Straight at the compare-and-set, not only in the route: claim_download
    is the only thing that sets download_mode='local'."""
    job = _downloading_job(con, created_local=False)
    assert not db.claim_download(con, job['id'], USER, 300, machine=DESKTOP)
    ok = _downloading_job(con, created_local=True)
    assert db.claim_download(con, ok['id'], USER, 300, machine=DESKTOP)


# ---------------------------------------------------------------- ytdl-web-7
# The " -- " scan itself lives with the em-dash one it extends:
# tests/test_no_em_dash.py::test_no_double_hyphen_in_editor_facing_strings.
