"""The 2026-09-18 hunt, ytdl/web's half (webapps-tools group, CR-286).

One section per finding id, so `grep -rn ytdl-web-4 tests/` lands on the test
as well as on the code. Every test here fails on the source before the fix
beside it.
"""
import re
from pathlib import Path

import pytest

from tests.conftest import PROJECTS, USER
from tests.test_local_download import (  # noqa: F401  (fleet is a fixture)
    FRESH_YTDLP, OTHER, _claim_body, _identity_header, fleet, SECRET, TOKEN)
from ytdlweb import config, db, routes_api, worker

APP_JS = Path(__file__).resolve().parents[1] / 'static' / 'app.js'


def _gone_root(tmp_path, monkeypatch, free_gb=200):
    """The leftover mount point: PROJECTS_ROOT exists, the project folder does
    not, and disk_usage answers happily for the container's own overlay."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': free_gb * 10 ** 9})())
    return root


def _downloading_url_job(con, ids=('aaaaaaaaaaa',), **over):
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(
        con, USER, '', '', slug, label,
        [{'video_id': v, 'url': f'https://youtu.be/{v}'} for v in ids], **over)
    db.mark_pending(con, job_id)
    db.set_phase(con, job_id, 'downloading')
    return db.get_job(con, job_id)


# ---------------------------------------------------------------- ytdl-web-2

def test_the_workers_no_room_note_names_the_lost_share_not_a_full_disk(
        con, tmp_path, monkeypatch):
    """`_refuse_if_full` asks whether the tree is there; the worker's copy of
    the same two numbers did not, so the executor path emitted the exact
    sentence CR-263a exists to stop an admin acting on."""
    _gone_root(tmp_path, monkeypatch, free_gb=2)
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    job = _downloading_url_job(con, created_local=True)
    rows = db.pending_videos(con, job['id'])

    note = worker._no_room_note(job, rows, tmp_path / 'projects' / 'nowhere')

    assert note, 'no refusal at all on a full disk'
    assert 'Free some space' not in note, note
    assert 'lost the share' in note, note


def test_a_present_tree_still_earns_the_full_disk_sentence(con, tmp_path,
                                                           monkeypatch):
    """The tree guard must not become a way for the disk gate to stop
    working."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    (root / PROJECTS[0][1]).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 10 ** 8})())
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    job = _downloading_url_job(con, created_local=True)
    rows = db.pending_videos(con, job['id'])

    note = worker._no_room_note(job, rows, root / PROJECTS[0][1])

    assert note and 'Free some space' in note, note


# ---------------------------------------------------------------- ytdl-web-4

def test_a_pasted_job_is_measured_at_the_press(client, con, tmp_path,
                                               monkeypatch):
    """The YTWEB-9 guard lived in `start_download`, which a paste never passes
    through, and the worker's backstop needed YTDL_LOCAL_DOWNLOAD on."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    (root / PROJECTS[0][1]).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 10 ** 8})())
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', False)

    r = client.post('/api/jobs/urls', json={
        'urls': ['https://www.youtube.com/watch?v=aaaaaaaaaaa'],
        'project_slug': PROJECTS[0][0], 'quality': '1080p', 'local': False})

    assert r.status_code == 409, r.text
    detail = r.json()['detail']
    assert detail['reason'] == 'disk_full', detail
    # ...and it names THIS page's button, not one that is not on it.
    assert 'DOWNLOAD' not in detail['detail'], detail
    assert 'GET LINKS' in detail['detail'], detail
    # ...and nothing was created: a refused paste must not burn a job row.
    assert con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0


def test_the_workers_backstop_covers_a_paste_with_the_flag_off(con, tmp_path,
                                                               monkeypatch):
    """The flag-off fleet is the shipped default, and it left the paste door
    unchecked on the executor as well."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    (root / PROJECTS[0][1]).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 10 ** 8})())
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', False)
    job = _downloading_url_job(con, created_local=False)
    rows = db.pending_videos(con, job['id'])

    note = worker._no_room_note(job, rows, root / PROJECTS[0][1])

    assert note and 'Free some space' in note, note


# ---------------------------------------------------------------- ytdl-web-5

def test_a_vanished_share_stops_the_download_even_when_there_is_room(
        con, tmp_path, monkeypatch):
    """The whole job used to SUCCEED into the container overlay, and the
    ledger then claimed clips at paths with no file behind them."""
    _gone_root(tmp_path, monkeypatch, free_gb=200)
    job = _downloading_url_job(con)

    assert routes_api.tree_is_gone(job) is True
    assert 'lost the share' in routes_api.tree_missing_note(job)


def test_a_root_that_cannot_be_read_is_never_called_gone(con, tmp_path,
                                                         monkeypatch):
    """Fails open on everything it cannot prove: a bind mount that is not
    there YET (boot order) must not refuse downloads."""
    monkeypatch.setattr(config, 'PROJECTS_ROOT', tmp_path / 'not-mounted-yet')
    job = _downloading_url_job(con)

    assert routes_api.tree_is_gone(job) is False
    assert routes_api.tree_missing_note(job) is None


# ---------------------------------------------------------------- ytdl-web-7

def test_the_db_module_defines_column_once():
    src = Path(db.__file__).read_text(encoding='utf-8')
    assert len(re.findall(r'^def _column\(', src, re.M)) == 1, \
        'two definitions of _column: an edit to one is a silent no-op'


# ---------------------------------------------------------------- ytdl-web-3

def test_a_job_that_failed_before_any_clip_still_offers_the_retry():
    """`_no_room_note` fires before the per-clip loop, so dl_failed is 0 and
    every row is `pending`: the button the note names was hidden."""
    src = APP_JS.read_text(encoding='utf-8')
    fn = src[src.index('function renderRetry('):]
    fn = fn[:fn.index('\nasync function ')]
    assert "dl_state === 'pending'" in fn, \
        'renderRetry still decides only on failed rows'
    assert 'stalled' in fn


# ---------------------------------------------------------------- ytdl-web-8

def test_the_unticked_note_does_not_call_a_paste_a_search():
    src = APP_JS.read_text(encoding='utf-8')
    assert 'this search was submitted with' not in src
    assert 'this job was submitted with' in src
