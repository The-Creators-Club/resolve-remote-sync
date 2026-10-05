"""CR-360 (2026-10-05): a bot-checked metadata pass no longer fails the search.

Measured live that day: with the studio's IP bot-checked, `ytsearch.search()`
(flat) came back in two seconds with entries, and every per-video
`extract_info` in `ytsearch.enrich()` was answered "Sign in to confirm you're
not a bot". `_phase_enrich` raised at the first such row, so jobs 117, 119 and
120 all went `failed` with enrich_done=0 -- while the requesting editor's own
companion, on a different IP, could have downloaded every clip.

What these pin:
  - the flat entry's details are KEPT on the row, without the search-page
    duration making the metadata pass skip the row;
  - a bot check stops the pass asking (no request after the trip), fills
    every row it did not get from the search page and carries on to the
    review with a warning, not a failure;
  - it still FAILS when nothing anywhere gave a duration;
  - an unknown upload date under a date range neither drops nor silently
    passes: the row stays relevant, arrives unticked and says why;
  - the server's one retry after a companion hand-back does not loop on the
    bot check.
"""
import sys
import threading
import types

import pytest

from tests.conftest import PROJECTS, USER
from tests.test_db import _V5_DDL
from tests.test_local_download import _claim_body, _job, fleet  # noqa: F401
from ytdlweb import claude_cli, config, db, worker
from ytdlweb.vendor import ytsearch

_BOT_MSG = ("ERROR: [youtube] aaaaaaaaaaa: Sign in to confirm you're not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication.")

TERM = 'algal reef controversy'


def _flat(duration=245, **over):
    """A flat search entry's extra keys, in the shape yt-dlp builds them from
    a results page's video renderer: no upload_date, thumbnails as a list."""
    entry = {
        'duration': duration,
        'channel': 'Flat Channel',
        'view_count': 4321,
        'thumbnails': [
            {'url': 'https://i.ytimg.com/vi/x/hqdefault.jpg', 'width': 480},
            {'url': 'https://i.ytimg.com/vi/x/hq720.jpg', 'width': 1280},
            {'url': 'https://i.ytimg.com/vi/x/default.jpg', 'width': 120},
        ],
        'live_status': None,
    }
    entry.update(over)
    return entry


def _wire(fake_youtube, ids, flat=None, meta=None, term=TERM):
    fake_youtube.results = {term: list(ids)}
    fake_youtube.flat = flat if flat is not None else {v: _flat() for v in ids}
    fake_youtube.meta = meta or {}
    return fake_youtube


def _rows(con, job_id):
    return {v['video_id']: v for v in db.videos(con, job_id)}


def _dated_job(con, job, **over):
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    over.setdefault('auto_terms', True)
    return db.create_job(con, USER, 'reef', 'reef', slug, label, **over)


# ------------------------------------------------------------- flat_meta

def test_flat_meta_keeps_what_the_results_page_carried():
    e = {'id': 'aaaaaaaaaaa', 'title': 'Reef', **_flat()}
    m = ytsearch.flat_meta(e)
    assert m == {'title': 'Reef', 'channel': 'Flat Channel', 'duration': 245,
                 'upload_date': None, 'view_count': 4321,
                 'thumbnail': 'https://i.ytimg.com/vi/x/hq720.jpg'}


def test_flat_meta_gives_a_live_entry_no_duration_and_trusts_no_junk():
    live = ytsearch.flat_meta({'id': 'x', **_flat(live_status='is_live')})
    assert live['duration'] is None
    upcoming = ytsearch.flat_meta({'id': 'x', **_flat(live_status='is_upcoming')})
    assert upcoming['duration'] is None
    junk = ytsearch.flat_meta({'id': 'x', 'duration': '4:05', 'view_count': True,
                               'upload_date': '3 years ago', 'thumbnails': [{}],
                               'uploader': 'Up'})
    assert junk['duration'] is None and junk['view_count'] is None
    assert junk['upload_date'] is None and junk['thumbnail'] is None
    assert junk['channel'] == 'Up'
    assert ytsearch.flat_meta({'id': 'x', 'upload_date': '20240102'})['upload_date'] \
        == '20240102'


# ------------------------------------------------- the search keeps the details

def test_flat_details_are_kept_without_skipping_the_metadata_pass(
        con, job, fake_claude, fake_youtube):
    """The duration goes to flat_duration, never to duration: the pass's to-do
    list is `duration IS NULL`, and every row must still be fetched for real."""
    ids = ['aaaaaaaaaaa', 'bbbbbbbbbbb']
    _wire(fake_youtube, ids)
    worker.run_job(con, job['id'])

    assert sorted(fake_youtube.enriched) == ids
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review' and not fresh['error']
    for v in _rows(con, job['id']).values():
        assert v['flat_duration'] == 245
        assert v['duration'] == 120.0, 'the fetched value, not the page one'
        assert v['meta_source'] is None
        assert v['channel'] == 'Test Channel'


# ------------------------------------------------------ the bot-checked pass

def test_a_bot_checked_pass_stops_asking_and_the_job_reaches_the_review(
        con, job, fake_claude, fake_youtube):
    ids = ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc']
    _wire(fake_youtube, ids, meta={'aaaaaaaaaaa': {'error': _BOT_MSG}})
    worker.run_job(con, job['id'])

    assert fake_youtube.enriched == ['aaaaaaaaaaa'], \
        'not one request after the first refusal'
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    assert fresh['error'] == worker.SEARCH_PAGE_NOTE
    assert fresh['enrich_total'] == 3 and fresh['enrich_done'] == 0
    for v in _rows(con, job['id']).values():
        assert v['meta_source'] == worker.META_FROM_SEARCH
        assert v['duration'] == 245
        assert v['channel'] == 'Flat Channel'
        assert v['view_count'] == 4321
        assert v['thumbnail'] == 'https://i.ytimg.com/vi/x/hq720.jpg'
        assert not v['meta_error']
        assert v['relevant'] == 1 and v['selected'] == 1
    # the judge still saw every row
    judged = [c[2] for c in fake_claude.calls if c[0] == 'relevance'][0]
    assert sorted(judged) == ids


def test_later_chunks_make_no_request_and_fetched_rows_keep_their_details(
        con, job, fake_claude, fake_youtube, monkeypatch):
    """ENRICH_WORKERS=1 -> chunks of 4, so five rows are two chunks. The trip
    lands on the second row of the first; the second is never handed to
    enrich at all."""
    monkeypatch.setattr(config, 'ENRICH_WORKERS', 1)
    ids = [c * 11 for c in 'abcde']   # the job's max_per_term is 5
    _wire(fake_youtube, ids, meta={'bbbbbbbbbbb': {'error': _BOT_MSG}})
    fake_claude_terms_off(fake_claude)
    worker.run_job(con, job['id'])

    assert fake_youtube.enriched == ['aaaaaaaaaaa', 'bbbbbbbbbbb']
    assert len(fake_youtube.enrich_calls) == 1
    rows = _rows(con, job['id'])
    assert rows['aaaaaaaaaaa']['meta_source'] is None
    assert rows['aaaaaaaaaaa']['duration'] == 120.0
    assert rows['aaaaaaaaaaa']['upload_date'] == '20260801'
    for vid in ids[1:]:
        assert rows[vid]['meta_source'] == worker.META_FROM_SEARCH, vid
        assert rows[vid]['duration'] == 245
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    assert fresh['enrich_done'] == 1, 'what was really fetched'


def fake_claude_terms_off(fake_claude):
    """Only the editor's own term, so every id comes from one search."""
    fake_claude.terms = []


def test_a_row_the_search_page_gave_no_duration_is_dropped_not_retried(
        con, job, fake_claude, fake_youtube):
    ids = ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc']
    _wire(fake_youtube, ids,
          flat={'aaaaaaaaaaa': _flat(),
                'bbbbbbbbbbb': _flat(duration=None),
                'ccccccccccc': _flat(live_status='is_live')},
          meta={'aaaaaaaaaaa': {'error': _BOT_MSG}})
    worker.run_job(con, job['id'])

    rows = _rows(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'ready_for_review'
    assert rows['aaaaaaaaaaa']['relevant'] == 1
    for vid in ('bbbbbbbbbbb', 'ccccccccccc'):
        assert rows[vid]['relevant'] == 0 and rows[vid]['selected'] == 0
        assert rows[vid]['relevance_note'] == 'live or no duration'
        assert rows[vid]['meta_source'] == worker.META_FROM_SEARCH

    # A second pass of the phase (it is resumable by design) asks for none of
    # them again: meta_source is what marks them done.
    before = list(fake_youtube.enriched)
    db.set_phase(con, job['id'], 'enriching')
    worker.run_job(con, job['id'])
    assert fake_youtube.enriched == before


def test_no_duration_anywhere_still_fails_with_the_bot_check_note(
        con, job, fake_claude, fake_youtube):
    ids = ['aaaaaaaaaaa', 'bbbbbbbbbbb']
    _wire(fake_youtube, ids, flat={v: _flat(duration=None) for v in ids},
          meta={'aaaaaaaaaaa': {'error': _BOT_MSG}})
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert fresh['error'] == worker.BOT_CHECK_NOTE
    # checked before anything was written
    assert all(v['meta_source'] is None for v in db.videos(con, job['id']))


# ---------------------------------------------------------- the date range

def test_an_unknown_date_under_a_range_stays_relevant_but_arrives_unticked(
        con, job, fake_claude, fake_youtube):
    mine = _dated_job(con, job, date_from='20190101', date_to='20191231')
    ids = ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc']
    fake_youtube.results = {'reef': ids}
    fake_youtube.flat = {v: _flat() for v in ids}
    # aaaa is fetched (a date inside the range), bbbb is refused, cccc never
    # asked. ENRICH_WORKERS is 2 here, so all three share one chunk.
    fake_youtube.meta = {'aaaaaaaaaaa': {'upload_date': '20190615'},
                         'bbbbbbbbbbb': {'error': _BOT_MSG}}
    worker.run_job(con, mine)

    rows = _rows(con, mine)
    assert db.get_job(con, mine)['phase'] == 'ready_for_review'
    assert rows['aaaaaaaaaaa']['selected'] == 1
    assert not rows['aaaaaaaaaaa']['relevance_note']
    for vid in ('bbbbbbbbbbb', 'ccccccccccc'):
        v = rows[vid]
        assert v['relevant'] == 1, 'not dropped for a fact nobody knows'
        assert v['selected'] == 0, 'not passed silently either'
        assert v['relevance_note'] == (
            'upload date unknown, so not checked against 2019-01-01 to '
            '2019-12-31: unticked until you look')
    # the judge saw them, and could still drop them
    judged = [c[2] for c in fake_claude.calls if c[0] == 'relevance'][0]
    assert set(judged) == set(ids)


def test_the_judge_dropping_an_unchecked_row_replaces_the_date_note(
        con, job, fake_claude, fake_youtube):
    mine = _dated_job(con, job, date_from='20190101')
    fake_youtube.results = {'reef': ['aaaaaaaaaaa']}
    fake_youtube.flat = {'aaaaaaaaaaa': _flat()}
    fake_youtube.meta = {'aaaaaaaaaaa': {'error': _BOT_MSG}}
    fake_claude.verdicts = {'aaaaaaaaaaa': (False, 'a cooking video')}
    worker.run_job(con, mine)
    v = _rows(con, mine)['aaaaaaaaaaa']
    assert v['relevant'] == 0 and v['relevance_note'] == 'a cooking video'


def test_a_period_search_with_no_range_ticks_search_page_rows_as_usual(
        con, job, fake_claude, fake_youtube):
    """`period` is YouTube's own filter on the results URL, so the search page
    the details came from was already limited to it."""
    mine = _dated_job(con, job, period='month')
    fake_youtube.results = {'reef': ['aaaaaaaaaaa']}
    fake_youtube.flat = {'aaaaaaaaaaa': _flat()}
    fake_youtube.meta = {'aaaaaaaaaaa': {'error': _BOT_MSG}}
    worker.run_job(con, mine)
    v = _rows(con, mine)['aaaaaaaaaaa']
    assert v['relevant'] == 1 and v['selected'] == 1 and not v['relevance_note']
    assert fake_youtube.searched[0][2] == 'month'


def test_an_enriched_row_with_no_date_is_still_kept_ticked_under_a_range(
        con, job, fake_claude, fake_youtube):
    """The pre-CR-360 rule for a FETCHED row is unchanged: "cannot tell"
    never drops it. Only search-page rows arrive unticked."""
    mine = _dated_job(con, job, date_from='20190101')
    fake_youtube.results = {'reef': ['aaaaaaaaaaa']}
    fake_youtube.meta = {'aaaaaaaaaaa': {'upload_date': None}}
    worker.run_job(con, mine)
    v = _rows(con, mine)['aaaaaaaaaaa']
    assert v['relevant'] == 1 and v['selected'] == 1 and not v['relevance_note']


# ------------------------------------------------------ the two warnings

def test_a_degraded_filter_keeps_the_search_page_warning_after_its_prefix(
        con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, ['aaaaaaaaaaa'], meta={'aaaaaaaaaaa': {'error': _BOT_MSG}})
    fake_claude.relevance_error = claude_cli.ClaudeError(
        claude_cli.ERR_AUTH, 'not logged in')
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    # the SPA's hint lookup matches the prefix at the very start
    assert fresh['error'].startswith(f'{claude_cli.ERR_AUTH} {worker.DEGRADED_NOTE}. ')
    assert worker.SEARCH_PAGE_NOTE.rstrip('.') in fresh['error']
    assert not fresh['error'].endswith('.'), 'hintFor appends ". <hint>"'


def test_the_warning_is_user_visible_text_without_an_em_dash():
    for text in (worker.SEARCH_PAGE_NOTE,):
        assert '—' not in text and '--' not in text


# ------------------------------------------- the real enrich() and abort_if

class _BotYtDlp:
    def __init__(self, bot=()):
        self.order = []
        self.lock = threading.Lock()
        self.bot = set(bot)

    def module(self):
        outer = self

        class YoutubeDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def extract_info(self, url, download=False):
                vid = url.rsplit('=', 1)[-1]
                with outer.lock:
                    outer.order.append(vid)
                if vid in outer.bot:
                    raise RuntimeError(_BOT_MSG)
                return {'id': vid, 'webpage_url': url, 'title': vid,
                        'duration': 12.0}

        return types.SimpleNamespace(YoutubeDL=YoutubeDL)


def test_the_real_enrich_stops_requesting_once_abort_if_trips(monkeypatch):
    fake = _BotYtDlp(bot=['aaaaaaaaaaa'])
    monkeypatch.setitem(sys.modules, 'yt_dlp', fake.module())
    ids = [c * 11 for c in 'abcd']
    entries = [{'id': v, 'url': f'https://www.youtube.com/watch?v={v}'} for v in ids]
    sleeps = []
    out = ytsearch.enrich(entries, jobs=1, pause=0.5, sleeper=sleeps.append,
                          abort_if=lambda r: worker._bot_checked(r.get('error')))

    assert fake.order == ['aaaaaaaaaaa']
    assert sleeps == [0.5], 'no pacing spent on requests that were not made'
    assert [r['id'] for r in out] == ids
    assert 'not a bot' in out[0]['error']
    assert all(r.get('aborted') for r in out[1:])


def test_the_real_enrich_without_abort_if_is_unchanged(monkeypatch):
    fake = _BotYtDlp(bot=['aaaaaaaaaaa'])
    monkeypatch.setitem(sys.modules, 'yt_dlp', fake.module())
    ids = [c * 11 for c in 'ab']
    entries = [{'id': v, 'url': f'https://www.youtube.com/watch?v={v}'} for v in ids]
    out = ytsearch.enrich(entries, jobs=1, pause=0, sleeper=lambda _s: None)
    assert fake.order == ids
    assert not any(r.get('aborted') for r in out)


# ------------------------------------------------------------- migration 015

def test_a_v14_database_gains_the_flat_columns_and_runs_once(tmp_path):
    con = db.connect(tmp_path / 'v14.db')
    con.executescript(_V5_DDL)
    for version in range(6, 15):
        db._apply_migration(con, db._MIGRATIONS[version][0])
    con.execute('PRAGMA user_version = 14')
    con.execute("INSERT INTO jobs(created_by,term,term_dir,project_slug,"
                "project_label,phase,created_at,updated_at) VALUES(?,'reef',"
                "'reef','s','2026/FF5/Energy','done','x','x')", (USER,))
    job_id = con.execute('SELECT id FROM jobs').fetchone()['id']
    con.execute("INSERT INTO job_videos(job_id,video_id,url,duration) "
                "VALUES(?,'aaaaaaaaaaa','u',12)", (job_id,))
    con.commit()
    assert 'meta_source' not in db._columns(con, 'job_videos')

    db.ensure_schema(con)
    db.ensure_schema(con)

    assert db._MIGRATIONS[15][0] == '015_job_videos_flat_meta.sql'
    assert db._MIGRATIONS[15][1](con) is True
    assert max(db._MIGRATIONS) == db.CURRENT_SCHEMA_VERSION == 15
    assert con.execute('PRAGMA user_version').fetchone()[0] == 15
    old = con.execute('SELECT * FROM job_videos').fetchone()
    assert old['flat_duration'] is None and old['meta_source'] is None
    assert old['duration'] == 12
    con.close()


def test_add_video_without_flat_details_is_what_it_always_was(con, job):
    assert db.add_video(con, job['id'], 'aaaaaaaaaaa', 'u', 'T')
    assert not db.add_video(con, job['id'], 'aaaaaaaaaaa', 'u', 'other')
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['title'] == 'T' and v['duration'] is None
    assert v['flat_duration'] is None and v['channel'] is None


# ------------------------------------- the server's retry after a hand-back

def _bot_downloader(monkeypatch, tried):
    def bot_checked(url, outdir, quality='best', **_kw):
        tried.append(url.rsplit('=', 1)[-1])
        raise RuntimeError(_BOT_MSG)
    monkeypatch.setattr(worker.downloader, 'download', bot_checked)


def test_a_bot_checked_retry_after_a_hand_back_ends_done_not_failed(
        fleet, client, con, project_root, monkeypatch):  # noqa: F811
    """The editor's machine fetched one clip and failed two; the server's one
    retry is bot-checked on the FIRST of them. One request, both clips left
    failed with a note that says why and what to press, and the job `done`
    with a warning -- the clip the editor fetched is not a failed job."""
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    tried = []
    _bot_downloader(monkeypatch, tried)
    job = _job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'))
    job_id = job['id']
    fleet.post(f'/api/jobs/{job_id}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job_id}/clips/aaaaaaaaaaa/status',
               json={'state': 'done',
                     'filepath_rel': 'Test Channel - a [aaaaaaaaaaa].mp4'})
    for vid in ('bbbbbbbbbbb', 'ccccccccccc'):
        fleet.post(f'/api/jobs/{job_id}/clips/{vid}/status',
                   json={'state': 'failed', 'error': 'HTTP Error 403'})

    worker.run_job(con, job_id)

    assert tried == ['bbbbbbbbbbb'], 'not one request after the bot check'
    fresh = db.get_job(con, job_id)
    assert fresh['phase'] == 'done'
    assert fresh['error'] == worker.HANDBACK_JOB_NOTE
    assert (fresh['dl_done'], fresh['dl_failed']) == (1, 2)
    for vid in ('bbbbbbbbbbb', 'ccccccccccc'):
        v = db.get_video(con, job_id, vid)
        assert v['dl_state'] == 'failed'
        assert v['dl_error'] == worker.HANDBACK_CLIP_NOTE
    assert db.get_video(con, job_id, 'aaaaaaaaaaa')['dl_state'] == 'done'
    assert (project_root / 'reef' / 'manifest.json').is_file()
    for text in (worker.HANDBACK_CLIP_NOTE, worker.HANDBACK_JOB_NOTE):
        assert '—' not in text and '--' not in text

    # ...and it stays stopped: nothing re-queues a done job by itself.
    assert db.claim_next_job(con) is None
    worker.run_job(con, job_id)
    assert tried == ['bbbbbbbbbbb']

    # [ RETRY 2 FAILED ] is POST download on the done job. It clears the
    # server pin, so the editor's own machine can claim the retry, and the
    # warning does not survive into the new run.
    assert client.post(f'/api/jobs/{job_id}/download').status_code == 200
    again = db.get_job(con, job_id)
    assert again['phase'] == 'downloading' and again['error'] is None
    assert again['mode_lock'] is None and again['claimed_by'] is None
    assert fleet.post(f'/api/jobs/{job_id}/claim',
                      json=_claim_body()).status_code == 200
    assert db.get_video(con, job_id, 'bbbbbbbbbbb')['dl_state'] == 'pending'


def test_a_job_downloading_on_the_server_from_the_start_still_fails_fast(
        con, project_root, monkeypatch):
    """No companion ever claimed it: the server is the only executor, so a bot
    check there is the whole job's answer and the cookies.txt note stands."""
    tried = []
    _bot_downloader(monkeypatch, tried)
    job = _job(con)
    assert job['claimed_by'] is None
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert 'YTDL_COOKIES_FILE' in fresh['error']
    assert tried == ['aaaaaaaaaaa']
    assert db.get_video(con, job['id'], 'bbbbbbbbbbb')['dl_state'] == 'pending'


def test_a_reclaimed_job_still_fails_fast(fleet, con, project_root,
                                          monkeypatch):  # noqa: F811
    """A lease that EXPIRED (the laptop closed) is not a hand-back: the
    reclaim clears claimed_by, the server owns the whole remaining run, and a
    bot check there is fatal exactly as before."""
    tried = []
    _bot_downloader(monkeypatch, tried)
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    con.execute("UPDATE jobs SET lease_expires_at='2020-01-01T00:00:00+00:00' "
                'WHERE id=?', (job['id'],))
    con.commit()
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'failed'
    assert len(tried) == 1
