"""The 2026-09-18b mediums wave, ytdl/web's half (ytdl group, CR-305).

One section per finding id, so `grep -rn ytdl-web-1 tests/` lands on the test
as well as on the code. Every test here fails on the source as it stood after
the 2026-09-18 pass (CR-286K/L), which is what these two findings are about.
"""
from pathlib import Path

from tests.conftest import PROJECTS, USER
from ytdlweb import config, db, routes_api, worker

APP_JS = Path(__file__).resolve().parents[1] / 'static' / 'app.js'


def _url_job(con, ids, **over):
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(
        con, USER, '', '', slug, label,
        [{'video_id': v, 'url': f'https://youtu.be/{v}'} for v in ids], **over)
    db.mark_pending(con, job_id)
    db.set_phase(con, job_id, 'downloading')
    return db.get_job(con, job_id)


# ---------------------------------------------------------------- ytdl-web-1

def test_a_failed_jobs_poll_carries_the_count_the_retry_offer_needs(
        client, con):
    """The page decides the retry offer from `dl_pending` on the poll.

    It cannot come from the manifest: poll() skips the manifest fetch for a
    terminal failure and a reload onto #job=<id> has none at all, so the job
    that failed before its first clip (no room, tree gone) showed no button.
    """
    job = _url_job(con, ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'])
    db.set_phase(con, job['id'], 'failed')

    r = client.get(f'/api/jobs/{job["id"]}')

    assert r.status_code == 200, r.text
    assert r.json()['job']['dl_pending'] == 3, r.json()['job']


def test_a_job_with_nothing_owed_is_offered_no_retry(client, con):
    """The count must be able to say zero, or the button is always on."""
    job = _url_job(con, ['aaaaaaaaaaa'])
    con.execute("UPDATE job_videos SET dl_state='done' WHERE job_id=?",
                (job['id'],))
    db.set_phase(con, job['id'], 'done')

    r = client.get(f'/api/jobs/{job["id"]}')

    assert r.json()['job']['dl_pending'] == 0, r.json()['job']


def test_render_retry_reads_the_poll_not_only_the_manifest():
    src = APP_JS.read_text(encoding='utf-8')
    fn = src[src.index('function renderRetry('):]
    fn = fn[:fn.index('\nasync function ')]
    assert 'job.dl_pending' in fn, \
        'renderRetry still counts pending rows in a manifest a failed job has not got'


# ---------------------------------------------------------------- ytdl-web-2

def _tree(tmp_path, monkeypatch, free_bytes):
    routes_api._free_cache.clear()
    root = tmp_path / 'projects'
    (root / PROJECTS[0][1]).mkdir(parents=True)
    monkeypatch.setattr(config, 'PROJECTS_ROOT', root)
    monkeypatch.setattr(routes_api.shutil, 'disk_usage',
                        lambda p: type('u', (), {'free': free_bytes})())
    return root


def test_forty_pasted_links_are_refused_with_six_gb_free(client, con, tmp_path,
                                                         monkeypatch):
    """A paste carries no duration anywhere, so the estimate is 0 and the flat
    2 GB floor accepted 40 links into a project with 6 GB left - the exact
    scenario CR-286L claimed. The floor is per CLIP now."""
    _tree(tmp_path, monkeypatch, 6 * 1000 ** 3)
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', False)
    urls = [f'https://www.youtube.com/watch?v={chr(97 + i)}aaaaaaaaaa'
            for i in range(20)] + \
           [f'https://www.youtube.com/watch?v={chr(97 + i)}bbbbbbbbbb'
            for i in range(20)]

    r = client.post('/api/jobs/urls', json={
        'urls': urls, 'project_slug': PROJECTS[0][0], 'quality': '1080p',
        'local': False})

    assert r.status_code == 409, r.text
    assert r.json()['detail']['reason'] == 'disk_full', r.json()
    assert con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0


def test_one_pasted_link_still_passes_the_same_six_gb(client, con, tmp_path,
                                                      monkeypatch):
    """The per-clip floor may only RAISE the need: a single link on a disk with
    6 GB on it was always allowed and must stay allowed, or the guard becomes a
    new way for a download to be impossible."""
    _tree(tmp_path, monkeypatch, 6 * 1000 ** 3)
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', False)

    r = client.post('/api/jobs/urls', json={
        'urls': ['https://www.youtube.com/watch?v=aaaaaaaaaaa'],
        'project_slug': PROJECTS[0][0], 'quality': '1080p', 'local': False})

    assert r.status_code == 200, r.text


def test_the_workers_backstop_uses_the_same_floor(con, tmp_path, monkeypatch):
    """One helper, both callers: a floor in the press guard alone is not a
    floor - the worker is the executor for every paste."""
    root = _tree(tmp_path, monkeypatch, 6 * 1000 ** 3)
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', False)
    job = _url_job(con, [f'{chr(97 + i)}aaaaaaaaaa' for i in range(26)]
                   + [f'{chr(97 + i)}bbbbbbbbbb' for i in range(14)])
    rows = db.pending_videos(con, job['id'])

    note = worker._no_room_note(job, rows, root / PROJECTS[0][1])

    assert note and 'Free some space' in note, note


def test_space_needed_is_the_flat_floor_when_a_paste_is_small():
    rows = [{'video_id': 'a', 'url': 'u', 'duration': None}]
    estimate, need = routes_api.space_needed(rows, '1080p')

    assert estimate == 0
    assert need == routes_api.UNKNOWN_ESTIMATE_FLOOR
