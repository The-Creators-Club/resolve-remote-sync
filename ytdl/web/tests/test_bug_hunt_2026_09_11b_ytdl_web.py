"""Regression tests for the 2026-09-11b hunt's ytdl-web findings (CR-263).

The hunt was OF the morning's fix pass (CR-244), so most of these pin the
NEIGHBOUR a fix opened rather than the fix itself: one section per finding id,
so `grep -rn ytdl-web-b-2 tests/` lands on the test as well as on the code.
"""
import unicodedata

import pytest

from tests.conftest import PROJECTS, USER
from ytdlweb import config, db, routes_api, worker


def _ready_job(con, seconds=3600, **over):
    """A job at ready_for_review with one sizeable clip selected: what the
    DOWNLOAD press is dispatched from."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label, **over)
    db.add_video(con, job_id, 'aaaaaaaaaaa', 'u')
    db.set_video(con, job_id, 'aaaaaaaaaaa', duration=seconds)
    db.set_phase(con, job_id, 'ready_for_review')
    return db.get_job(con, job_id)


def _free(monkeypatch, cell):
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': cell[0]})())


# -------------------------------------------------------------- ytdl-web-b-1

def test_the_press_after_the_share_comes_back_is_measured_fresh(
        client, con, tmp_path, monkeypatch):
    """ytdl-web-1's guard raised BEFORE ytdl-web-2's cache drop, so the
    overlay's 2 GB - measured while the bind mount was gone - stayed in the
    cache for the rest of its 60 s TTL, keyed on the whole tree. The press
    after the admin remounts then said "free some space" about a share with
    900 GB on it."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    root.mkdir()                                # the leftover mount point
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    free = [2 * 10 ** 9]
    _free(monkeypatch, free)
    job = _ready_job(con)

    first = client.post(f'/api/jobs/{job["id"]}/download')
    assert first.status_code == 409, first.json()
    assert first.json()['detail']['reason'] == 'tree_missing'

    # The share comes back INSIDE the 60 s TTL, with room to spare.
    (root / PROJECTS[0][1]).mkdir(parents=True)
    free[0] = 900 * 10 ** 9
    second = client.post(f'/api/jobs/{job["id"]}/download')
    assert second.status_code == 200, second.json()


# -------------------------------------------------------------- ytdl-web-b-2

def test_the_server_will_not_execute_a_local_job_onto_a_full_tree(
        con, tmp_path, monkeypatch, fake_downloader):
    """ytdl-web-4 skips the press-time disk gate for a job created local, on
    the reasoning that the editor's own disk is the one that matters. But a
    created-local job is only OFFERED: with no tray running the NAS worker is
    the executor, and it had no free-space check at all - so YTWEB-9's one
    sentence became N opaque per-clip ENOSPC failures again."""
    routes_api._free_cache.clear()
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    monkeypatch.setattr(config, 'LOCAL_CLAIM_GRACE_SECONDS', 0.01)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 2 * 10 ** 8})())
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label,
                           created_local=True)
    db.add_video(con, job_id, 'aaaaaaaaaaa', 'u')
    db.set_video(con, job_id, 'aaaaaaaaaaa', duration=3600)
    db.mark_pending(con, job_id)
    db.set_job(con, job_id, dl_total=1)
    db.set_phase(con, job_id, 'downloading')

    worker.run_job(con, job_id)

    fresh = db.get_job(con, job_id)
    assert fresh['phase'] == 'failed', dict(fresh)
    assert 'free' in (fresh['error'] or '').lower(), fresh['error']
    # Not one byte fetched, and the rows are still pending: the retry after
    # the admin frees space re-queues exactly them.
    assert fake_downloader.calls == []
    assert db.get_video(con, job_id, 'aaaaaaaaaaa')['dl_state'] == 'pending'


def test_a_server_job_with_room_still_downloads(
        con, tmp_path, monkeypatch, fake_downloader, project_root):
    """The other half: the new worker-side gate fails OPEN and must never
    become a new way for a download to be impossible."""
    routes_api._free_cache.clear()
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    monkeypatch.setattr(config, 'LOCAL_CLAIM_GRACE_SECONDS', 0.01)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 900 * 10 ** 9})())
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label,
                           created_local=True)
    db.add_video(con, job_id, 'aaaaaaaaaaa', 'u')
    db.set_video(con, job_id, 'aaaaaaaaaaa', duration=60)
    db.mark_pending(con, job_id)
    db.set_phase(con, job_id, 'downloading')

    worker.run_job(con, job_id)
    assert db.get_job(con, job_id)['phase'] == 'done'
    assert len(fake_downloader.calls) == 1, fake_downloader.calls


# -------------------------------------------------------------- ytdl-web-b-3

def _doctored(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding='utf-8')
    return p


def test_the_double_hyphen_scan_covers_the_page_copy(tmp_path):
    """ytdl-web-7's scan has one arm, the Python one, and app.js writes every
    toast, banner and status cell on this page. The gate is measured by
    DOCTORING each surface and asking whether any test in the suite's own
    module catches it - not by asserting a helper exists."""
    from tests import test_no_em_dash as gate

    surfaces = {
        'app.js': _doctored(tmp_path, 'app.js',
                            "toast('queued -- and downloading');\n"),
        'index.html': _doctored(tmp_path, 'index.html',
                                '<p>queued -- and downloading</p>\n'),
    }
    for name, path in surfaces.items():
        caught = []
        for attr in dir(gate):
            if not attr.startswith('test_'):
                continue
            fn = getattr(gate, attr)
            try:
                fn(path)
            except AssertionError as e:
                if ' -- ' in str(e) or 'double' in str(e).lower():
                    caught.append(attr)
            except Exception:
                continue        # a Python-only arm handed an .html file
        assert caught, (f"nothing in test_no_em_dash.py scans {name} for "
                        f"' -- ' (ytdl-web-b-3)")


# -------------------------------------------------------------- ytdl-web-b-4

def test_a_job_created_on_the_server_costs_no_grace_period(con, monkeypatch):
    """ytdl-web-5 made created_local=0 a hard refusal at the claim CAS, so no
    machine can ever claim such a job. Holding the door open for 4 s per job
    anyway is dead time on a single-threaded worker, and the log line claims
    the requester was given first refusal, which is no longer true."""
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    monkeypatch.setattr(config, 'LOCAL_CLAIM_GRACE_SECONDS', 60.0)
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label,
                           created_local=False)
    db.set_phase(con, job_id, 'downloading')

    def never(_seconds):
        raise AssertionError('it waited for a claim nothing can make')

    assert worker._await_local_claim(con, job_id, sleep=never) is False


def test_a_job_created_local_still_gets_its_grace(con, monkeypatch):
    """The half that must not regress: CR-34's whole point."""
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    monkeypatch.setattr(config, 'LOCAL_CLAIM_GRACE_SECONDS', 0.3)
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label,
                           created_local=True)
    db.set_phase(con, job_id, 'downloading')
    ticks = {'n': 0}

    def sleep(_seconds):
        ticks['n'] += 1

    assert worker._await_local_claim(con, job_id, sleep=sleep) is False
    assert ticks['n'] > 0


# -------------------------------------------------------------- ytdl-web-b-5

def test_an_unreadable_tree_is_stat_ed_once_a_minute_not_once_a_press(
        tmp_path, monkeypatch):
    """The cache exists because "a stat per request against a NAS mount that
    has gone away is a request that hangs, not one that answers" - which is
    exactly the answer ytdl-web-6's refactor stopped caching."""
    routes_api._free_cache.clear()
    monkeypatch.setattr(config, 'PROJECTS_ROOT', tmp_path / 'projects')
    calls = {'n': 0}

    def hung(_p):
        calls['n'] += 1
        raise OSError('the mount is not answering')

    monkeypatch.setattr(routes_api.shutil, 'disk_usage', hung)
    outdir = config.PROJECTS_ROOT / '2026/FF5/Energy/Youtube/reef'

    assert routes_api.free_bytes_at(outdir) is None
    first = calls['n']
    assert first > 0
    assert routes_api.free_bytes_at(outdir) is None
    assert calls['n'] == first, 'the negative answer was not cached'


# -------------------------------------------------------------- ytdl-web-b-6

@pytest.mark.skipif(
    unicodedata.normalize('NFD', 'Simalčík') == 'Simalčík',
    reason='this platform has no distinct decomposed spelling to test with')
def test_a_decomposed_project_label_is_not_a_missing_tree(
        client, con, tmp_path, monkeypatch):
    """CR-90: a path a Mac reported is not `==` a path anything else reported.
    The tree guard stats PROJECTS_ROOT/<label> with the label's own bytes, so
    an NFD label against an NFC folder reads as "the server has lost the
    share" when the real fault is a full disk."""
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    label_nfc = unicodedata.normalize('NFC', '2026/FF5/Šimalčík')
    label_nfd = unicodedata.normalize('NFD', label_nfc)
    if (root / label_nfd).exists():
        pytest.skip('this filesystem folds the two spellings together')
    (root / label_nfc).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': 2 * 10 ** 9})())
    slug, _label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label_nfd)
    db.add_video(con, job_id, 'aaaaaaaaaaa', 'u')
    db.set_video(con, job_id, 'aaaaaaaaaaa', duration=3600)
    db.set_phase(con, job_id, 'ready_for_review')

    r = client.post(f'/api/jobs/{job_id}/download')
    assert r.status_code == 409, r.json()
    assert r.json()['detail']['reason'] == 'disk_full', r.json()


# --------------------------------------------------------------- regression-26

def test_the_job_says_whether_it_was_created_local(con):
    """The SPA re-reads its own switch at dispatch time, so an editor who
    ticks "this computer" after the search was submitted hands a job the claim
    CAS can only refuse. The page can only skip that hand-off if the job row
    tells it what the job was CREATED with."""
    slug, label, _ = PROJECTS[0]
    server = db.create_job(con, USER, 'reef', 'reef', slug, label,
                           created_local=False)
    local = db.create_job(con, USER, 'reef', 'reef', slug, label,
                          created_local=True)
    assert db.job_dict(db.get_job(con, server))['created_local'] is False
    assert db.job_dict(db.get_job(con, local))['created_local'] is True


def test_the_spa_skips_the_hand_off_for_a_job_created_on_the_server():
    """The source half of the same finding: `dispatchLocal` takes the job's
    created_local and every call site passes it. The behavioural half is
    test_static_app.py's `a_job_created_on_the_server_is_not_offered_here`."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / 'static' / 'app.js').read_text(
        encoding='utf-8')
    body = js[js.index('async function dispatchLocal('):
              js.index('// §9: the executor, named')]
    assert 'createdLocal === false' in body, body
    assert js.count('dispatchLocal(') >= 4      # the definition and three calls
