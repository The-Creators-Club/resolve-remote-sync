"""The pipeline, walked end to end with claude and yt-dlp replaced by seams.

`worker.run_job()` is called directly rather than through the thread: it is
synchronous, it takes the connection it should use, and the suite sets
YTDL_WORKER=0 so no daemon thread is racing these rows. That is the same reason
the phase functions each name their own successor -- a job can be picked up in
any phase, by a test or by a container that just restarted.
"""
import json
import os
import sqlite3
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from tests.conftest import OTHER_USER, PROJECTS, USER
from ytdlweb import claude_cli, config, db, routes_api, worker
from ytdlweb.vendor import ytsearch


def _wire(fake_youtube, results, meta=None, fail_terms=()):
    fake_youtube.results = results
    fake_youtube.meta = meta or {}
    fake_youtube.fail_terms = set(fail_terms)
    return fake_youtube


def test_the_whole_pipeline_walks_to_ready_for_review(
        con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {
        'algal reef controversy': ['aaaaaaaaaaa'],
        'algal reef taiwan': ['bbbbbbbbbbb'],
        'lng terminal protest': ['ccccccccccc'],
        '藻礁 三接 爭議': ['ddddddddddd'],
    })
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    assert fresh['terms_total'] == 4          # the editor's own term + 3 generated
    assert fresh['terms_done'] == 4
    assert fresh['candidates'] == 4
    assert fresh['enrich_total'] == 4 and fresh['enrich_done'] == 4
    assert {v['video_id'] for v in db.videos(con, job['id'])} == {
        'aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc', 'ddddddddddd'}
    # everything auto-selected (REQ 4)
    assert all(v['selected'] for v in db.videos(con, job['id']))


def test_the_editors_own_term_is_searched_first_and_marked_user(
        con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {})
    worker.run_job(con, job['id'])
    terms = db.terms(con, job['id'])
    assert terms[0]['term'] == 'algal reef controversy'
    assert terms[0]['source'] == 'user'
    assert [t['source'] for t in terms[1:]] == ['claude'] * 3


def test_chinese_terms_arrive_with_their_english_gloss(
        con, job, fake_claude, fake_youtube):
    """REQ 5: without the gloss the manifest is unreadable to most of the fleet."""
    _wire(fake_youtube, {})
    worker.run_job(con, job['id'])
    zh = [t for t in db.terms(con, job['id']) if t['lang'] == 'zh']
    assert len(zh) == 1
    assert zh[0]['english_gloss'] == 'algal reef third LNG terminal dispute'
    assert all(t['english_gloss'] is None
               for t in db.terms(con, job['id']) if t['lang'] == 'en')


def test_a_video_found_by_two_terms_is_attributed_to_both(
        con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {
        'algal reef controversy': ['aaaaaaaaaaa'],
        'algal reef taiwan': ['aaaaaaaaaaa', 'bbbbbbbbbbb'],
    })
    worker.run_job(con, job['id'])

    terms = {t['term']: t['id'] for t in db.terms(con, job['id'])}
    links = db.term_ids_by_video(con, job['id'])
    assert set(links['aaaaaaaaaaa']) == {terms['algal reef controversy'],
                                         terms['algal reef taiwan']}
    assert links['bbbbbbbbbbb'] == [terms['algal reef taiwan']]
    # counted once as a candidate, twice as an attribution
    assert db.get_job(con, job['id'])['candidates'] == 2


def test_one_failing_term_does_not_fail_the_job(con, job, fake_claude, fake_youtube):
    """YouTube throttling one query out of twenty is normal; nineteen terms'
    worth of manifest is worth having."""
    _wire(fake_youtube,
          {'algal reef controversy': ['aaaaaaaaaaa'], 'algal reef taiwan': ['bbbbbbbbbbb']},
          fail_terms=['algal reef taiwan'])
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'ready_for_review'
    hit = {t['term']: t['hits'] for t in db.terms(con, job['id'])}
    assert hit['algal reef controversy'] == 1
    assert hit['algal reef taiwan'] == 0


def test_unavailable_videos_are_kept_but_dropped_from_the_selection(
        con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb']},
          meta={'bbbbbbbbbbb': {'error': 'Private video'}})
    worker.run_job(con, job['id'])
    bad = db.get_video(con, job['id'], 'bbbbbbbbbbb')
    assert bad['meta_error'] == 'Private video'
    assert bad['relevant'] == 0 and bad['selected'] == 0


def test_a_live_stream_is_dropped_mechanically(con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']},
          meta={'aaaaaaaaaaa': {'duration': None}})
    worker.run_job(con, job['id'])
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['relevant'] == 0 and v['relevance_note'] == 'live or no duration'


def test_a_video_over_the_length_cap_is_dropped_mechanically(
        con, job, fake_claude, fake_youtube):
    """Admin request 2026-08-14: a search harvest skips anything over 30
    minutes. Soft, like a Claude verdict -- the card stays in the manifest so
    the editor can overrule -- and the judge never sees (never spends tokens
    on) a card the length cap already decided. Pasted-link jobs bypass the
    filter phase entirely, so a deliberately pasted long video still
    downloads."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb']},
          meta={'bbbbbbbbbbb': {'duration': 1801.0}})
    worker.run_job(con, job['id'])

    dropped = db.get_video(con, job['id'], 'bbbbbbbbbbb')
    assert dropped['relevant'] == 0 and dropped['selected'] == 0
    assert dropped['relevance_note'] == 'over 30 minutes'
    assert len(db.videos(con, job['id'])) == 2
    judged = [call[2] for call in fake_claude.calls if call[0] == 'relevance']
    assert all('bbbbbbbbbbb' not in ids for ids in judged)


def test_a_video_at_exactly_the_cap_is_kept(con, job, fake_claude, fake_youtube):
    """The cap is "over half an hour", not "half an hour and up"."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']},
          meta={'aaaaaaaaaaa': {'duration': 1800.0}})
    worker.run_job(con, job['id'])
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['relevant'] == 1


def test_claudes_verdicts_deselect_but_keep_the_rows(con, job, fake_claude, fake_youtube):
    """Filtered-out cards stay in the manifest so the editor can overrule."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb']})
    fake_claude.verdicts = {'aaaaaaaaaaa': (True, ''),
                            'bbbbbbbbbbb': (False, 'gaming stream, unrelated')}
    worker.run_job(con, job['id'])
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['relevant'] == 1
    dropped = db.get_video(con, job['id'], 'bbbbbbbbbbb')
    assert dropped['relevant'] == 0 and dropped['selected'] == 0
    assert dropped['relevance_note'] == 'gaming stream, unrelated'
    assert len(db.videos(con, job['id'])) == 2


def test_a_claude_failure_in_the_filter_degrades_it_does_not_fail_the_job(
        con, job, fake_claude, fake_youtube):
    """An editor with an unfiltered manifest and a banner is fine; an editor
    with no manifest because a CLI was logged out has lost the whole search."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    fake_claude.relevance_error = claude_cli.ClaudeError(
        claude_cli.ERR_AUTH, 'not logged in')
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    # the banner carries the FAILING call's prefix, so the SPA still tells the
    # editor to fetch an admin rather than "claude returned junk"
    assert fresh['error'] == f'{claude_cli.ERR_AUTH} {worker.DEGRADED_NOTE}'
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['relevant'] == 1


def test_a_claude_failure_generating_terms_fails_the_job_with_its_prefix(
        con, job, fake_claude, fake_youtube):
    """The prefix is the contract with the SPA: 'an admin must run the one-time
    login' and 'the model returned junk' are different calls to action."""
    fake_claude.term_error = claude_cli.ClaudeError(
        claude_cli.ERR_AUTH, 'claude is not logged in on the server')
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert fresh['error'].startswith('claude_auth:')
    assert claude_cli.health()['claude'] == 'unauthenticated'


def test_a_cancel_stops_the_walk_between_terms(con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    db.request_cancel(con, job['id'])
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'cancelled'


# ------------------------------------------------------- the shot types
# The editor's checkboxes are stored on the job row, and BOTH Claude calls have
# to be given them: terms generated for aerials and then filtered for
# interviews would throw away most of what the search just found.

def test_the_jobs_shot_types_reach_both_claude_calls(
        con, job, fake_claude, fake_youtube):
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    mine = db.create_job(con, USER, 'algal reef controversy', 'algal reef',
                         slug, label, shot_types=['aerial', 'interview'],
                         auto_terms=True)
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, mine)

    assert fake_claude.shot_types == [('terms', ('aerial', 'interview')),
                                      ('relevance', ('aerial', 'interview'))]


def test_a_job_that_ticked_nothing_asks_for_no_bias_not_the_defaults(
        con, job, fake_claude, fake_youtube):
    """'' on the row is the editor's own choice and must survive to the prompt
    builder, which is what turns it into a neutral search."""
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    none = db.create_job(con, USER, 'algal reef controversy', 'algal reef',
                         slug, label, shot_types=[], auto_terms=True)
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, none)

    assert [s for _stage, s in fake_claude.shot_types] == [(), ()]


def test_an_old_job_row_is_re_run_with_the_defaults(
        con, job, fake_claude, fake_youtube):
    """A job queued before the checkboxes existed is a job that ran under the
    fixed visual bias -- migration 005 leaves it holding the six default ticks,
    and boot recovery must re-run it as the search it was."""
    assert db.get_job(con, job['id'])['shot_types'] == db.encode_shot_types(None)
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, job['id'])

    assert [s for _stage, s in fake_claude.shot_types] == [
        db.DEFAULT_SHOT_TYPES, db.DEFAULT_SHOT_TYPES]


# -------------------------------------------------------- the search mode
# The rubric is on the job row for the same reason the ticks are: a job re-run
# from `queued` after a container restart must be expanded AND filtered under
# the mode the editor chose, not under whatever the default has become.


def test_the_jobs_mode_reaches_both_ai_calls(con, job, fake_claude, fake_youtube):
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    mine = db.create_job(con, USER, 'algal reef controversy', 'algal reef',
                         slug, label, mode='news', auto_terms=True)
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, mine)

    assert fake_claude.modes == [('terms', 'news'), ('relevance', 'news')]
    # ...with the mode's own preset, since no boxes were sent with it
    assert [s for _stage, s in fake_claude.shot_types] == [
        claude_cli.COVERAGE_KEYS, claude_cli.COVERAGE_KEYS]


def test_an_old_job_row_is_re_run_as_a_visuals_search(
        con, job, fake_claude, fake_youtube):
    """A job queued before the modes existed ran the only search there was.
    Migration 009 leaves it holding 'visuals', and boot recovery must re-run it
    as that -- a manifest filtered on the news rubric would throw away the
    footage it went looking for."""
    assert db.get_job(con, job['id'])['mode'] == claude_cli.MODE_VISUALS
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, job['id'])

    assert [m for _stage, m in fake_claude.modes] == ['visuals', 'visuals']


# --------------------------------------------------- the candidate ceiling
# 2026-08-11: 24 terms -> 336 candidates -> one metadata call each, and YouTube
# refused the NAS's IP at 112 of them. The ceiling is enforced where candidates
# are ACCUMULATED, so what it bounds is the number of metadata calls -- not the
# length of the manifest after they have all been made.

def _capped_job(con, con_job, cap, user=USER, term='algal reef controversy'):
    """A fresh search job for `user` with an explicit candidate ceiling."""
    slug, label, _ = PROJECTS[1]
    if con_job is not None:
        db.set_phase(con, con_job['id'], 'cancelled')   # one active job each
    job_id = db.create_job(con, user, term, 'algal reef', slug, label,
                           max_candidates=cap, auto_terms=True)
    return db.get_job(con, job_id)


def test_the_ceiling_bounds_the_metadata_calls_not_just_the_manifest(
        con, job, fake_claude, fake_youtube):
    """The assertion that matters is the CALL COUNT at the seam: a cap applied
    to the finished manifest would leave this number at 6 and the fleet blocked
    exactly as before."""
    mine = _capped_job(con, job, 2)
    _wire(fake_youtube, {
        'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb'],
        'algal reef taiwan': ['ccccccccccc', 'ddddddddddd'],
        'lng terminal protest': ['eeeeeeeeeee'],
        '藻礁 三接 爭議': ['fffffffffff'],
    })
    worker.run_job(con, mine['id'])

    assert len(fake_youtube.enriched) == 2, fake_youtube.enriched
    assert {v['video_id'] for v in db.videos(con, mine['id'])} == {
        'aaaaaaaaaaa', 'bbbbbbbbbbb'}
    fresh = db.get_job(con, mine['id'])
    assert fresh['candidates'] == 2
    assert fresh['enrich_total'] == 2 and fresh['enrich_done'] == 2
    assert fresh['phase'] == 'ready_for_review'
    # every term is still searched and still counted: 24 flat searches is not
    # the volume in question, and terms_done drives the progress bar
    assert fresh['terms_done'] == fresh['terms_total'] == 4
    assert [t['hits'] for t in db.terms(con, mine['id'])] == [2, 2, 1, 1]


def test_a_hit_past_the_ceiling_is_dropped_rather_than_attributed(
        con, job, fake_claude, fake_youtube):
    """A term_id pointing at a video with no row would inflate the chip counts
    over a grid that cannot show it (YTDL-38's shape). A term that re-finds a
    video already ON the job is still attributed -- that costs nothing."""
    mine = _capped_job(con, job, 2)
    _wire(fake_youtube, {
        'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb'],
        'algal reef taiwan': ['aaaaaaaaaaa', 'ccccccccccc'],
    })
    worker.run_job(con, mine['id'])

    terms = {t['term']: t['id'] for t in db.terms(con, mine['id'])}
    links = db.term_ids_by_video(con, mine['id'])
    assert set(links['aaaaaaaaaaa']) == {terms['algal reef controversy'],
                                         terms['algal reef taiwan']}
    assert 'ccccccccccc' not in links
    counts = db.term_hit_counts(con, mine['id'])
    assert counts[terms['algal reef taiwan']] == 1, 'a dropped hit was counted'


def test_the_default_ceiling_applies_to_a_job_that_named_none(
        con, job, fake_claude, fake_youtube):
    """The fixture job is an ordinary one: no dropdown, no cap in the request.
    It must still be bounded -- unbounded is the incident."""
    assert db.get_job(con, job['id'])['max_candidates'] == 100
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['candidates'] == 1


def test_a_resumed_job_re_runs_with_the_ceiling_it_was_submitted_with(
        con, job, fake_claude, fake_youtube):
    """Boot recovery wipes a mid-pipeline job's rows and re-runs it from
    `queued`; the number has to come off the ROW, not from whatever the default
    has become since."""
    mine = _capped_job(con, job, 2)
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb',
                                                    'ccccccccccc']})
    db.set_phase(con, mine['id'], 'searching')
    db.reset_stale_jobs(con)
    assert db.get_job(con, mine['id'])['phase'] == 'queued'

    worker.run_job(con, mine['id'])
    assert len(fake_youtube.enriched) == 2
    assert db.get_job(con, mine['id'])['max_candidates'] == 2


def test_the_ceiling_counts_rows_already_on_a_resumed_job(
        con, job, fake_claude, fake_youtube):
    """`downloading` is the phase boot recovery keeps, but a search phase that
    is re-entered with rows already written must treat the ceiling as absolute
    rather than per-run -- otherwise a flapping container multiplies it."""
    mine = _capped_job(con, job, 2)
    db.add_video(con, mine['id'], 'zzzzzzzzzzz', 'u')
    db.add_video(con, mine['id'], 'yyyyyyyyyyy', 'u')
    con.commit()
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    db.set_phase(con, mine['id'], 'generating_terms')
    worker.run_job(con, mine['id'])

    assert {v['video_id'] for v in db.videos(con, mine['id'])} == {
        'zzzzzzzzzzz', 'yyyyyyyyyyy'}
    assert len(fake_youtube.enriched) == 2


def test_a_bot_check_is_still_classified_when_the_ceiling_is_in_force(
        con, job, fake_claude, fake_youtube):
    """YTDL-21 must not be masked by the cap: a short manifest that stopped
    because YouTube refused the IP is a different problem from one that stopped
    because the editor asked for 50, and only one of them has a fix."""
    mine = _capped_job(con, job, 2)
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb',
                                                    'ccccccccccc']},
          meta={'aaaaaaaaaaa': {'error': _BOT_MSG}})
    worker.run_job(con, mine['id'])

    fresh = db.get_job(con, mine['id'])
    assert fresh['phase'] == 'failed'
    assert 'YTDL_COOKIES_FILE' in fresh['error']


def test_a_url_job_never_consults_the_ceiling(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    """It does no searching, so there is nothing to accumulate: a paste of more
    links than the default ceiling downloads all of them."""
    job = _url_job(con, [f'{i:011d}' for i in range(12)])
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['max_candidates'] == 100        # the unused column default
    assert fresh['dl_done'] == 12
    assert fake_youtube.searched == [] and fake_youtube.enriched == []


# ------------------------------------------------------------ enrich pacing
# The download phase paced itself (YTDL_DOWNLOAD_PAUSE=3) and the metadata pass
# -- the busier of the two -- did not pace at all: 4 pool threads, no delay.
# That is what 112 calls in well under a minute looked like from YouTube's side.

def test_the_worker_hands_the_configured_pacing_to_the_metadata_pass(
        con, job, fake_claude, fake_youtube):
    """The seam records what it was called with, because the pacing is only
    real if the phase actually passes it down."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb']})
    worker.run_job(con, job['id'])

    assert fake_youtube.enrich_calls, 'the metadata pass never ran'
    for call in fake_youtube.enrich_calls:
        assert call['jobs'] == config.ENRICH_WORKERS
        assert call['pause'] == config.ENRICH_PAUSE
    # the defaults are the conservative ones, not batch_dl's unpaced four
    assert config.ENRICH_WORKERS <= 4 and config.ENRICH_PAUSE > 0


class _FakeYtDlp:
    """The smallest `yt_dlp` ytsearch.enrich uses: a context manager with
    extract_info. Injected into sys.modules because the real import is inside
    the function (vendor/__init__.py) and this suite has no yt-dlp."""

    def __init__(self, fail=()):
        self.order = []                  # the ids actually asked for, in order
        self.lock = threading.Lock()     # the pool is real; the list is not safe
        self.fail = set(fail)

    def module(self):
        outer = self

        class YoutubeDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def extract_info(self, url, download=False):
                vid = url.rsplit('=', 1)[-1]
                with outer.lock:
                    outer.order.append(vid)
                if vid in outer.fail:
                    raise RuntimeError(f'ERROR: [youtube] {vid}: Private video')
                return {'id': vid, 'webpage_url': url, 'title': f'{vid} title',
                        'channel': 'ch', 'duration': 12.0,
                        'upload_date': '20260801', 'view_count': 5,
                        'thumbnail': None}

        return types.SimpleNamespace(YoutubeDL=YoutubeDL)


def _enrich(monkeypatch, ids, **kw):
    """Run the REAL ytsearch.enrich against a faked yt_dlp. -> (results, sleeps)."""
    sleeps = []
    fake = _FakeYtDlp(fail=kw.pop('fail', ()))
    monkeypatch.setitem(sys.modules, 'yt_dlp', fake.module())
    entries = [{'id': v, 'url': f'https://www.youtube.com/watch?v={v}'} for v in ids]
    out = ytsearch.enrich(entries, sleeper=sleeps.append, **kw)
    return out, sleeps, fake


def test_every_metadata_request_waits_its_turn(monkeypatch):
    """One sleep per REQUEST, including each chunk's first: worker.py calls
    enrich() once per chunk, so skipping the first would hand back a free
    request every chunk."""
    ids = [f'{i:011d}' for i in range(6)]
    out, sleeps, _ = _enrich(monkeypatch, ids, jobs=2, pause=0.75)
    assert [r['id'] for r in out] == ids, 'the input order must survive the pool'
    assert sleeps == [0.75] * 6


def test_the_pacing_is_between_requests_not_per_thread(monkeypatch):
    """The gate is held during the wait, so the ceiling is 1/pause requests a
    second whatever YouTube's latency is. Per-thread sleeps would have made the
    real rate a function of that latency -- the number nobody could measure
    when this went wrong."""
    src = (Path(ytsearch.__file__)).read_text(encoding='utf-8')
    body = src[src.index('def enrich('):]
    assert 'with gate:' in body and 'sleeper(pause)' in body
    # ...and the sleep is inside the lock, not after it
    assert body.index('with gate:') < body.index('sleeper(pause)') < \
        body.index('def fetch(')


def test_the_metadata_pass_is_still_bounded_and_still_parallel(monkeypatch):
    """Paced, not serialised: a 100-candidate search must not become an
    afternoon. The worker count is what keeps the wait and the request
    overlapping."""
    ids = [f'{i:011d}' for i in range(4)]
    out, sleeps, _ = _enrich(monkeypatch, ids, jobs=2, pause=0)
    assert sleeps == [], 'pause=0 must not sleep at all'
    assert len(out) == 4


def test_pacing_does_not_swallow_a_dead_video(monkeypatch):
    """One dead video still comes back as an 'error' row rather than raising --
    which is also how the bot check reaches worker._bot_checked (YTDL-21)."""
    ids = ['aaaaaaaaaaa', 'bbbbbbbbbbb']
    out, sleeps, _ = _enrich(monkeypatch, ids, jobs=1, pause=0.5,
                             fail=['bbbbbbbbbbb'])
    assert sleeps == [0.5, 0.5]
    assert out[0]['title'] == 'aaaaaaaaaaa title'
    assert 'Private video' in out[1]['error']


def test_the_progress_callback_still_fires_once_per_entry(monkeypatch):
    """It is what moves the SPA's metadata counter, and it is called from a
    pool thread -- the pacing must not have moved it out of one."""
    seen = []
    ids = [f'{i:011d}' for i in range(3)]
    _enrich(monkeypatch, ids, jobs=2, pause=0.1,
            progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_enrich_defaults_to_the_configured_pacing(monkeypatch):
    """A caller that names neither gets the container's settings, so there is
    no path that quietly goes back to unpaced."""
    monkeypatch.setattr(config, 'ENRICH_PAUSE', 0.25)
    monkeypatch.setattr(config, 'ENRICH_WORKERS', 1)
    _out, sleeps, _f = _enrich(monkeypatch, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    assert sleeps == [0.25, 0.25]


# ------------------------------------------------------------------ download

def _to_review(con, job, fake_claude, fake_youtube, ids):
    _wire(fake_youtube, {'algal reef controversy': list(ids)})
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'ready_for_review'


def test_download_writes_files_a_ledger_row_and_a_manifest(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root):
    _to_review(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    assert db.mark_pending(con, job['id']) == 2
    db.set_phase(con, job['id'], 'downloading')
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done' and fresh['dl_done'] == 2 and fresh['dl_failed'] == 0

    outdir = project_root / job['term_dir']
    files = sorted(p.name for p in outdir.iterdir())
    assert 'manifest.json' in files
    assert sum(1 for f in files if f.endswith('.mp4')) == 2
    assert sum(1 for f in files if f.endswith('.credits.json')) == 2

    ledger = db.ledger_get(con, 'aaaaaaaaaaa')
    assert ledger['project_slug'] == PROJECTS[0][0]
    assert ledger['rel_path'].startswith('Youtube/' + job['term_dir'] + '/')
    assert ledger['downloaded_by'] == USER

    # provenance: the query, the terms WITH glosses, and per-video attribution
    mf = json.loads((outdir / 'manifest.json').read_text(encoding='utf-8'))
    assert mf['query'] == 'algal reef controversy'
    assert mf['project'] == PROJECTS[0][1]
    assert any(t['english_gloss'] for t in mf['terms'])
    assert mf['videos'][0]['found_by'] == ['algal reef controversy']


def test_a_failed_video_is_counted_and_the_job_still_finishes(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root):
    """`failed` is reserved for the pipeline dying; 1 of 2 clips failing is a
    done job with a visible per-row error."""
    fake_downloader.fail_ids = {'bbbbbbbbbbb'}
    _to_review(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    db.mark_pending(con, job['id'])
    db.set_phase(con, job['id'], 'downloading')
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done'
    assert (fresh['dl_done'], fresh['dl_failed']) == (1, 1)
    bad = db.get_video(con, job['id'], 'bbbbbbbbbbb')
    assert bad['dl_state'] == 'failed' and 'yt-dlp said no' in bad['dl_error']


def test_a_video_already_in_the_ledger_is_skipped_not_fetched(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root):
    """Selection can never override dedupe: the re-check happens immediately
    before the bandwidth is spent, because another job may have fetched it
    between review and download."""
    _to_review(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])
    db.mark_pending(con, job['id'])
    db.set_phase(con, job['id'], 'downloading')
    db.ledger_add(con, 'aaaaaaaaaaa', 't', 'c', '2025-ff4-nuclear',
                  '2025/FF4/Nuclear', 'other term', 'Youtube/other term/x.mp4')

    worker.run_job(con, job['id'])
    assert fake_downloader.calls == []
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'skipped' and v['duplicate'] == 1
    assert v['duplicate_of'] == '2025/FF4/Nuclear/other term'


def test_a_cancel_stops_between_videos(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root):
    _to_review(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    db.mark_pending(con, job['id'])
    db.set_phase(con, job['id'], 'downloading')
    db.request_cancel(con, job['id'])
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'cancelled'
    assert fake_downloader.calls == []


def test_a_restarted_download_job_resumes_and_does_not_refetch(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root):
    """The container-restart case: yt-dlp's .part is resumable, but anything
    that actually landed must not be fetched twice."""
    _to_review(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    db.mark_pending(con, job['id'])
    db.set_phase(con, job['id'], 'downloading')
    worker.run_job(con, job['id'])
    assert len(fake_downloader.calls) == 2

    # ...the container restarts mid-job: boot recovery keeps the job and puts
    # the in-flight row back to pending.
    db.set_video(con, job['id'], 'aaaaaaaaaaa', dl_state='downloading')
    db.set_phase(con, job['id'], 'downloading')
    db.reset_stale_jobs(con)
    fake_downloader.calls.clear()
    worker.run_job(con, job['id'])

    # The file is on disk and in the ledger, so the re-run skips it entirely.
    assert fake_downloader.calls == []
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'skipped'


def test_a_restarted_mid_pipeline_job_starts_over_cleanly(
        con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    db.set_phase(con, job['id'], 'searching')
    db.add_term(con, job['id'], 'stale term', 'en', 'claude')
    db.add_video(con, job['id'], 'zzzzzzzzzzz', 'u')

    db.reset_stale_jobs(con)
    assert db.get_job(con, job['id'])['phase'] == 'queued'
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    ids = {v['video_id'] for v in db.videos(con, job['id'])}
    assert 'zzzzzzzzzzz' not in ids               # the stale row is gone
    assert 'stale term' not in {t['term'] for t in db.terms(con, job['id'])}


def _download(con, job, fake_claude, fake_youtube, ids):
    """Walk the fixture job from queued to the end of the download phase."""
    _to_review(con, job, fake_claude, fake_youtube, ids)
    db.mark_pending(con, job['id'])
    db.set_phase(con, job['id'], 'downloading')
    worker.run_job(con, job['id'])


def test_a_failed_conversion_leaves_nothing_that_blocks_the_next_attempt(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """YTDL-3 (2026-08-11): the download landed, ensure_edit_ready then died
    (ffmpeg error, full disk) -- and the original stayed in the term folder
    under its `... [id].mp4` name: 0600, unledgered, VP9 that Resolve cannot
    decode. Every later search read that `[id]` and told the editor the fleet
    already had the clip, with no route back through the UI."""
    def half_landed(url, outdir, quality='best', **_kw):
        vid = url.rsplit('=', 1)[-1]
        (Path(outdir) / f'Test Channel - {vid} title [{vid}].mp4').write_bytes(b'vp9')
        raise RuntimeError('Edit-ready conversion failed: ffmpeg said no')

    monkeypatch.setattr(worker.downloader, 'download', half_landed)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'failed'
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None, 'nothing landed; nothing to ledger'

    outdir = project_root / job['term_dir']
    assert ytsearch.existing_ids(outdir) == set()
    assert worker.mark_duplicates(con, job) == 0, 'the retry must not be blocked'
    # kept, not deleted -- the bytes are still footage, just disowned
    assert [p.name for p in outdir.iterdir() if p.name.endswith('.failed')]


def test_a_pre_existing_file_survives_a_failed_attempt(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """Only what THIS attempt left behind is disowned: a clip that was already
    in the folder belongs to someone else's job (and to the ledger)."""
    outdir = project_root / job['term_dir']
    outdir.mkdir(parents=True, exist_ok=True)
    keep = outdir / 'Test Channel - old [aaaaaaaaaaa].mp4'
    keep.write_bytes(b'landed earlier')

    def boom(url, outdir_, quality='best', **_kw):
        raise RuntimeError('yt-dlp said no')

    monkeypatch.setattr(worker.downloader, 'download', boom)
    _to_review(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    db.mark_pending(con, job['id'])
    db.set_phase(con, job['id'], 'downloading')
    worker.run_job(con, job['id'])

    assert keep.exists()


def test_a_download_reporting_no_file_is_a_failure_not_an_empty_ledger_row(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """YTDL-15 (2026-08-11): download() can return a summary with no filepath.
    Recording that `done` wrote a ledger row with an EMPTY rel_path -- a
    permanent "the fleet already has this" pointing at nothing, and the ledger
    never cascades, so only hand-editing ytdl.db could undo it."""
    def no_file(url, outdir, quality='best', **_kw):
        return {'title': 't', 'channel': 'c', 'thumbnail': None,
                'filepath': None, 'sidecar': None}

    monkeypatch.setattr(worker.downloader, 'download', no_file)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    fresh = db.get_job(con, job['id'])
    assert (fresh['dl_done'], fresh['dl_failed']) == (0, 1)
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'failed'
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None
    assert db.ledger_ids(con) == set()


# --------------------------------------------------- a truncated DASH stream

class DownloadError(RuntimeError):
    """yt-dlp's exception class, by NAME.

    This suite has no yt_dlp at all (vendor/__init__.py) and
    worker._stream_truncated matches the class by name for exactly that reason,
    so a stand-in spelled the same way is the whole seam. A subclass, because
    the classifier walks the MRO -- yt-dlp's real one is a subclass of
    YoutubeDLError.
    """


# Verbatim from the incident (SAQBbd1Rxmo, 2026-08-13): f137 (1080p avc) died
# this way on every attempt, from the NAS worker and from the base rig alike.
_TRUNCATED = ('ERROR: unable to download video data: Got error: 8 bytes read, '
              '10288457 more expected. Giving up after 10 retries')


class TruncatingDownloader:
    """A downloader whose ONE bad rung always ends short, like YouTube's did.

    Every other rung writes a real file, because the dedupe re-check greps the
    destination folder for `[id]` names and a mock that wrote nothing would let
    a broken dedupe pass. The bad rung leaves the `.f137.mp4.part` the live
    incident left behind, spelled the way the outtmpl spells it.
    """

    def __init__(self, bad_quality='1080p', error=None, bad_everywhere=False):
        self.bad_quality = bad_quality
        self.bad_everywhere = bad_everywhere      # nothing works, at any rung
        self.error = error or DownloadError(_TRUNCATED)
        self.calls = []

    def download(self, url, outdir, quality='best', **_kw):
        vid = url.rsplit('=', 1)[-1]
        self.calls.append((vid, quality))
        if self.bad_everywhere or quality == self.bad_quality:
            part = Path(outdir) / f'Test Channel - {vid} title [{vid}].f137.mp4.part'
            part.write_bytes(b'x' * 8)
            raise self.error
        path = Path(outdir) / f'Test Channel - {vid} title [{vid}].mp4'
        path.write_bytes(b'fake video')
        side = path.with_suffix('.credits.json')
        side.write_text('{}', encoding='utf-8')
        return {'title': f'{vid} title', 'channel': 'Test Channel',
                'video_url': url, 'thumbnail': None, 'duration': 120,
                'filepath': str(path), 'sidecar': str(side)}


def test_the_fallback_rung_is_the_downloaders_own_next_one_down():
    """One quality table, not two: the retry downloads with the format string
    format_selector builds from this same dict."""
    assert worker._lower_quality('1080p') == '720p'
    assert worker._lower_quality('2160p') == '1440p'
    assert worker._lower_quality('720p') == '480p'
    assert worker._lower_quality('480p') is None       # the bottom rung
    assert worker._lower_quality('audio') is None      # not on this ladder
    # `best` is UNCAPPED, so a cap above the source's own height re-selects the
    # identical stream; the 1080p rung asks for AVC and is a different format.
    assert worker._lower_quality('best') == '1080p'


def test_a_truncated_stream_is_retried_one_rung_down_and_the_row_says_so(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """SAQBbd1Rxmo (2026-08-13): YouTube served f137 (1080p avc) truncated to
    two different IPs, from a fresh start, for hours -- while f136 (720p) came
    down fine from both minutes later. The clip failed outright and the editor
    got NOTHING, when a downloadable rung was one line of format string away."""
    fake = TruncatingDownloader(bad_quality='1080p')
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    assert job['quality'] == '1080p'
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert fake.calls == [('aaaaaaaaaaa', '1080p'), ('aaaaaaaaaaa', '720p')]
    fresh = db.get_job(con, job['id'])
    assert (fresh['dl_done'], fresh['dl_failed']) == (1, 0)

    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'done'
    # the downgrade is RECORDED: the clip is here, but not at the rung asked for
    assert v['dl_error'] == '1080p stream truncated by YouTube, fell back to 720p'
    assert db.ledger_get(con, 'aaaaaaaaaaa') is not None

    outdir = project_root / job['term_dir']
    assert [p.name for p in outdir.iterdir() if p.name.endswith('.part')] == [], \
        'the truncated .part is what the retry would have resumed from'


@pytest.mark.parametrize('exc', [
    # The bot check, a throttle and a dead network are MOMENTS, not formats:
    # downgrading quality on any of them would cost resolution nobody asked to
    # lose, on a clip that would have come down fine a minute later.
    DownloadError('ERROR: unable to download video data: HTTP Error 403: Forbidden'),
    DownloadError('ERROR: [youtube] SAQBbd1Rxmo: Unable to download API page'),
    # yt-dlp is still retrying this one itself -- "giving up after" is what says
    # the budget is spent and the FORMAT is the problem.
    DownloadError('WARNING: Got error: 8 bytes read, 10288457 more expected. '
                  'Retrying (attempt 3 of 10)'),
    # ...and the same words out of something that is not a DownloadError at all
    # (an ffmpeg failure, a bug in here) are not yt-dlp giving up on a format.
    RuntimeError('Got error: 8 bytes read, 10288457 more expected. '
                 'Giving up after 10 retries'),
])
def test_a_transient_failure_is_never_a_silent_quality_downgrade(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, exc):
    fake = TruncatingDownloader(bad_quality='1080p', error=exc)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert fake.calls == [('aaaaaaaaaaa', '1080p')], 'the 720p rung was tried'
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'failed' and str(exc)[:40] in v['dl_error']


def test_the_fallback_is_one_rung_not_a_walk_down_the_ladder(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """A bad afternoon on YouTube's side must not quietly put 480p footage in
    the canonical tree: one rung is what the incident needed, and a clip that
    fails at both is a failed clip."""
    fake = TruncatingDownloader(bad_everywhere=True)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert fake.calls == [('aaaaaaaaaaa', '1080p'), ('aaaaaaaaaaa', '720p')]
    fresh = db.get_job(con, job['id'])
    assert (fresh['dl_done'], fresh['dl_failed']) == (0, 1)
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'failed'
    # the row names both halves: what YouTube did, and that the fallback ran
    assert '1080p stream truncated' in v['dl_error']
    assert '720p retry failed too' in v['dl_error']
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None


def test_a_finally_failed_clip_takes_its_own_partials_and_nobody_elses(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """SAQBbd1Rxmo (2026-08-13): the give-up left a 10 MB
    `... [SAQBbd1Rxmo].f137.mp4.part` in the term folder forever -- the lane
    filters exclude `*.part` so it never syncs, but it sits in the CANONICAL
    tree as a corpse, and yt-dlp resumes a .part, so the next attempt starts
    from the poisoned bytes and dies the same way.

    Scoped to the `[id]` segment: the term folder is shared, and a neighbour's
    .part may belong to a download that is still running."""
    outdir = project_root / job['term_dir']
    outdir.mkdir(parents=True, exist_ok=True)
    neighbour = outdir / 'Test Channel - other [bbbbbbbbbbb].f137.mp4.part'
    neighbour.write_bytes(b'still downloading')
    unrelated = outdir / 'The .part standard explained [ccccccccccc].mp4'
    unrelated.write_bytes(b'a deliverable whose TITLE says .part')

    def truncated(url, outdir_, quality='best', **_kw):
        vid = url.rsplit('=', 1)[-1]
        for name in (f'A [{vid}].f137.mp4.part', f'A [{vid}].f137.mp4.ytdl',
                     f'A [{vid}].part-Frag7'):
            (Path(outdir_) / name).write_bytes(b'x')
        raise RuntimeError('yt-dlp said no')

    monkeypatch.setattr(worker.downloader, 'download', truncated)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'failed'
    left = sorted(p.name for p in outdir.iterdir())
    assert 'A [aaaaaaaaaaa].f137.mp4.part' not in left
    assert 'A [aaaaaaaaaaa].f137.mp4.ytdl' not in left
    assert 'A [aaaaaaaaaaa].part-Frag7' not in left
    assert neighbour.name in left, "another clip's resume state is not ours"
    assert unrelated.name in left, 'a deliverable is not a leftover (YTDL-17)'


def test_the_swap_note_and_the_reclaimable_space_reach_the_clip_row(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """YT-6: an editor with a `.converted` file in their term folder had
    nothing anywhere to explain the name. _swap_in's note went to the
    in-memory progress dict, which is cleared the instant the clip finishes."""
    outdir = project_root / job['term_dir']
    outdir.mkdir(parents=True, exist_ok=True)
    stuck = outdir / 'A [aaaaaaaaaaa].original.webm'
    stuck.write_bytes(b'x' * (3 * 1024 * 1024))

    def refuse(self, *a, **kw):
        raise OSError('Access is denied')

    monkeypatch.setattr(Path, 'unlink', refuse)

    def download(url, outdir_, quality='best', **_kw):
        vid = url.rsplit('=', 1)[-1]
        path = Path(outdir_) / f'A.converted [{vid}].mp4'
        path.write_bytes(b'fake video')
        return {'title': 'A', 'channel': 'C', 'video_url': url,
                'thumbnail': None, 'duration': 10, 'filepath': str(path),
                'sidecar': None,
                'note': f'original was in use, kept as A [{vid}].original.webm'}

    monkeypatch.setattr(worker.downloader, 'download', download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    row = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert row['dl_state'] == 'done'
    assert 'original was in use' in row['dl_error']
    assert '3 MB reclaimable' in row['dl_error']


# ------------------------------------------------------- pasted-link jobs

def _url_job(con, ids, user=USER):
    """A kind='urls' job for `ids`, exactly as routes_api.create_url_job makes
    one: rows already pending, no terms, phase queued -- and an EMPTY term and
    term_dir, which is what "into the project's Youtube root, no subfolder"
    looks like in the database (2026-08-11)."""
    slug, label, _ = PROJECTS[0]
    videos = [{'video_id': v, 'url': f'https://www.youtube.com/watch?v={v}'}
              for v in ids]
    job_id = db.create_url_job(con, user, routes_api.URL_JOB_TERM,
                               routes_api.URL_JOB_TERM_DIR, slug, label, videos)
    return db.get_job(con, job_id)


def test_a_url_job_walks_queued_straight_into_the_download_phase(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    """The whole feature: no term generation, no search, no enrichment, no
    filter -- the same download phase, into the same tree, with the same
    ledger and manifest."""
    job = _url_job(con, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done'
    assert (fresh['dl_done'], fresh['dl_failed']) == (2, 0)
    assert fake_claude.calls == [], 'a pasted link must never reach claude'
    assert fake_youtube.searched == [] and fake_youtube.enriched == []
    assert db.terms(con, job['id']) == []
    assert [c[0] for c in fake_downloader.calls] == ['aaaaaaaaaaa', 'bbbbbbbbbbb']


def test_a_url_job_lands_in_the_projects_youtube_root(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    """`<project>/Youtube/<clip>`, with NO subfolder at all (owner,
    2026-08-11: there is no term to sort individual downloads by). Still no
    deeper than the one level youtube_import walks -- it lists that level and
    files each folder into Master/Youtube/<folder>, and collects the loose
    clips in the root itself from companion 0.7.1."""
    job = _url_job(con, ['aaaaaaaaaaa'])
    worker.run_job(con, job['id'])

    clips = [p.name for p in project_root.iterdir() if p.suffix == '.mp4']
    assert clips == ['Test Channel - aaaaaaaaaaa title [aaaaaaaaaaa].mp4']
    assert project_root.name == 'Youtube'
    assert not [p for p in project_root.iterdir() if p.is_dir()], \
        'a paste invented a folder to sit in'
    assert [p.name for p in project_root.iterdir() if p.name.endswith('.credits.json')]

    # ...and the same ledger row a search job's download writes, minus the level
    row = db.ledger_get(con, 'aaaaaaaaaaa')
    assert row['rel_path'] == 'Youtube/' + clips[0]
    assert row['term_dir'] == '', 'the root is empty, not a folder name'
    assert row['project_slug'] == PROJECTS[0][0] and row['downloaded_by'] == USER
    assert row['job_id'] == job['id']
    # the badge an editor is shown has to name a folder that exists (YTDL-31),
    # and '<label>/' with nothing after it is not one
    assert db.ledger_where(row) == f'{PROJECTS[0][1]}/Youtube'
    assert db.ledger_map(con)['aaaaaaaaaaa'] == f'{PROJECTS[0][1]}/Youtube'

    mf = json.loads((project_root / f'manifest.{job["id"]}.json').read_text(
        encoding='utf-8'))
    assert mf['kind'] == 'urls' and mf['query'] == ''
    assert [v['id'] for v in mf['videos']] == ['aaaaaaaaaaa']


def test_two_pastes_do_not_overwrite_each_others_provenance(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    """A term folder belongs to one search, so `manifest.json` there is meant
    to be replaced by a re-run. The Youtube root belongs to every paste the
    project will ever receive -- one filename there would mean each paste
    silently destroyed the record of the last."""
    first = _url_job(con, ['aaaaaaaaaaa'])
    worker.run_job(con, first['id'])
    db.set_phase(con, first['id'], 'done')
    second = _url_job(con, ['bbbbbbbbbbb'])
    worker.run_job(con, second['id'])

    manifests = sorted(p.name for p in project_root.iterdir()
                       if p.name.startswith('manifest'))
    assert manifests == [f'manifest.{first["id"]}.json',
                         f'manifest.{second["id"]}.json']
    # ...and a SEARCH still writes the flat name into its own term folder
    assert worker.manifest_name({'id': 9, 'term_dir': 'algal reef'}) == 'manifest.json'


def test_a_pasted_link_the_project_already_has_names_the_folder_it_is_in(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    """The disk half of the dedupe, with the paste's outdir being the WHOLE
    Youtube tree: a clip that is really in a search's term folder must be
    reported as being there, not as loose in the root."""
    term_dir = project_root / 'algal reef'
    term_dir.mkdir(parents=True, exist_ok=True)
    (term_dir / 'Test Channel - old [aaaaaaaaaaa].mp4').write_bytes(b'landed earlier')

    job = _url_job(con, ['aaaaaaaaaaa'])
    worker.run_job(con, job['id'])

    assert fake_downloader.calls == [], 'it was already in the project'
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'skipped' and v['duplicate'] == 1
    assert v['duplicate_of'] == f'{PROJECTS[0][1]}/algal reef'


def test_a_url_jobs_rows_learn_their_title_from_the_download(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    """Nothing fetched metadata for these: without this the progress list names
    every clip by its 11-char id forever."""
    job = _url_job(con, ['aaaaaaaaaaa'])
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['title'] is None
    worker.run_job(con, job['id'])
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['title'] == 'aaaaaaaaaaa title'


def test_a_url_job_re_checks_the_ledger_immediately_before_spending_bandwidth(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    """The API checks the ledger when the links are pasted; another editor's
    job can land the same clip between then and the worker claiming this one."""
    job = _url_job(con, ['aaaaaaaaaaa'])
    db.ledger_add(con, 'aaaaaaaaaaa', 't', 'c', '2025-ff4-nuclear',
                  '2025/FF4/Nuclear', 'other term', 'Youtube/other term/x.mp4')
    worker.run_job(con, job['id'])

    assert fake_downloader.calls == []
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'skipped' and v['duplicate'] == 1
    assert v['duplicate_of'] == '2025/FF4/Nuclear/other term'
    assert db.get_job(con, job['id'])['phase'] == 'done'


def test_a_url_job_is_cancelled_between_videos_like_any_other(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    job = _url_job(con, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    db.request_cancel(con, job['id'])
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'cancelled'
    assert fake_downloader.calls == []


def test_a_url_job_is_claimed_by_the_same_serial_worker(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root):
    """One queue, oldest first: a paste does not jump the queue, and a search
    job already in flight is not disturbed by one."""
    links = _url_job(con, ['aaaaaaaaaaa'], user=OTHER_USER)
    assert db.claim_next_job(con)['id'] == job['id']
    db.set_phase(con, job['id'], 'done')
    assert db.claim_next_job(con)['id'] == links['id']


def test_a_url_job_widens_every_artifact_for_the_fleet_too(
        con, fake_claude, fake_youtube, fake_downloader, clean_projects,
        monkeypatch):
    """YTDL-45's contract is the download phase's, and a url job goes through
    exactly the same code -- so a 0600 clip invisible over SMB cannot come back
    through the new door.

    Deliberately WITHOUT the project_root fixture: the directory this job
    creates is now `Youtube` itself, and pre-creating it would leave nothing for
    ensure_outdir to widen (it only forces a mode on directories it made)."""
    asked = []
    monkeypatch.setattr(worker, '_chmod', lambda p, m: asked.append((Path(p).name, m)))
    job = _url_job(con, ['aaaaaaaaaaa'])
    worker.run_job(con, job['id'])

    modes = dict(asked)
    assert modes['Youtube'] == 0o2775
    assert modes[f'manifest.{job["id"]}.json'] == 0o664
    assert sum(1 for n, _ in asked if n.endswith('.mp4')) == 1
    assert sum(1 for n, _ in asked if n.endswith('.credits.json')) == 1


def test_a_failed_link_is_one_dead_video_not_a_dead_job(
        con, fake_claude, fake_youtube, fake_downloader, project_root):
    fake_downloader.fail_ids = {'aaaaaaaaaaa'}
    job = _url_job(con, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done' and (fresh['dl_done'], fresh['dl_failed']) == (1, 1)
    assert 'yt-dlp said no' in db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_error']
    # Nothing landed, so nothing is ledgered -- which is what makes "paste it
    # again" the retry for a url job (there is no review grid to press DOWNLOAD
    # in a second time, and the API would otherwise refuse it as a duplicate).
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None


# ---------------------------------------------------------------- the sweep

def test_the_sweep_takes_fragments_and_leaves_the_deliverables(project_root):
    """YTDL-17 (2026-08-11): `'.part' in name` also matched a title containing
    ".part". `.editready` was on the same list of things not to sweep, because
    it was _swap_in's fallback DELIVERABLE, ledgered under exactly that name.

    YT-6 (resilience sweep 2026-08-28) took that half away by renaming the
    fallback to `<title>.converted [id].mp4`, whose stem still ends in `[id]`.
    A `.editready` is now only ever ffmpeg's half-written output, so it is
    litter; the `.converted` deliverable is what must survive the sweep, and
    the title containing ".part" still must."""
    d = project_root / 'term'
    d.mkdir(parents=True, exist_ok=True)
    swept = ['A [aaaaaaaaaaa].f616.mp4.part', 'A [aaaaaaaaaaa].f616.mp4.ytdl',
             'A [aaaaaaaaaaa].part-Frag7', 'A [aaaaaaaaaaa].editready.mp4']
    kept = ['A.converted [aaaaaaaaaaa].mp4', 'A [bbbbbbbbbbb].mp4',
            'The .part standard explained [ccccccccccc].mp4', 'manifest.json']
    for name in swept + kept:
        p = d / name
        p.write_bytes(b'x')
        old = time.time() - worker.STALE_AFTER - 60
        os.utime(p, (old, old))

    worker._sweep_stale(d)
    assert sorted(p.name for p in d.iterdir()) == sorted(kept)


def test_the_sweep_takes_a_completed_per_format_stream_too(project_root):
    """COMP-BROLL-3 (2026-08-14): the litter nothing on either machine deleted.

    A 1080p rung is `bestvideo+bestaudio`, so yt-dlp renames
    `... [id].f137.mp4.part` to `... [id].f137.mp4` the moment that stream
    completes and keeps it for resume if the audio or the merge then fails. It
    is not a sweepable SUFFIX, `_landed_file` correctly refuses to read it as
    the clip, and it matches lane A's `+ *.mp4` include and no stignore line --
    so one abandoned job put a 1.4 GB video-only orphan in the canonical tree
    and on every editor with that project ticked, permanently. The local
    executor grew this rule the same day; both executors write into one tree
    and must leave the same things behind in it."""
    d = project_root / 'term'
    d.mkdir(parents=True, exist_ok=True)
    swept = ['A [aaaaaaaaaaa].f137.mp4', 'A [aaaaaaaaaaa].f251.webm',
             'A [aaaaaaaaaaa].temp.mp4', 'A [aaaaaaaaaaa].editready.mp4']
    # ...and the deliverable can never match: the outtmpl ends every finished
    # name in `[id].<ext>`, so its stem ends in `[id]` -- which is exactly why
    # YT-6 moved the fallback deliverable's marker in FRONT of the bracket
    kept = ['A [aaaaaaaaaaa].mp4', 'A.converted [aaaaaaaaaaa].mp4',
            'A [aaaaaaaaaaa].credits.json', 'manifest.json',
            # a locked-aside original is footage, and an AGE rule over a
            # shared folder must never be what deletes it (YT-6)
            'A [aaaaaaaaaaa].original.mp4']
    for name in swept + kept:
        p = d / name
        p.write_bytes(b'x')
        old = time.time() - worker.STALE_AFTER - 60
        os.utime(p, (old, old))

    worker._sweep_stale(d)
    assert sorted(p.name for p in d.iterdir()) == sorted(kept)


def test_a_completed_per_format_stream_is_never_the_clip_and_always_litter():
    """The two halves of the same rule, at the function that decides both:
    _sweepable says it is litter, and _landed_file (which anchors on `[id]` at
    the end of the stem) has always refused to read it as the clip."""
    for name in ('A [aaaaaaaaaaa].f137.mp4', 'A [aaaaaaaaaaa].temp.mp4',
                 'A [aaaaaaaaaaa].f137.mp4.part', 'A [aaaaaaaaaaa].part-Frag7',
                 # YT-6: no longer a possible deliverable, so now litter
                 'A [aaaaaaaaaaa].editready.mp4'):
        assert worker._sweepable(name) is True, name
    for name in ('A [aaaaaaaaaaa].mp4', 'A.converted [aaaaaaaaaaa].mp4',
                 'A [aaaaaaaaaaa].original.mp4',
                 'A [aaaaaaaaaaa].credits.json',
                 'The .part standard explained [ccccccccccc].mp4'):
        assert worker._sweepable(name) is False, name


def test_a_failed_clip_takes_its_completed_streams_with_it(project_root):
    """The id-scoped half: _clear_partials is what runs on a give-up, and it
    must now take the finished-but-unmerged stream as well -- while leaving a
    neighbour's alone, because the term folder is shared with clips that may
    still be downloading (SAQBbd1Rxmo)."""
    d = project_root / 'term'
    d.mkdir(parents=True, exist_ok=True)
    for name in ('A [aaaaaaaaaaa].f137.mp4', 'A [aaaaaaaaaaa].f140.m4a.part',
                 'B [bbbbbbbbbbb].f137.mp4', 'A [aaaaaaaaaaa].mp4.failed'):
        (d / name).write_bytes(b'x')
    worker._clear_partials(d, 'aaaaaaaaaaa')
    assert sorted(p.name for p in d.iterdir()) == [
        'A [aaaaaaaaaaa].mp4.failed', 'B [bbbbbbbbbbb].f137.mp4']


def test_a_locked_aside_original_is_retried_on_the_next_attempt(project_root):
    """YT-6 (resilience sweep 2026-08-28): when Resolve holds the file open,
    _swap_in renames the pre-conversion original to `... [id].original.<ext>`
    and NOTHING ever removed it -- a full second copy of every converted clip,
    matching lane A's `+ *.mp4`, in the canonical tree forever. The retry is
    id-scoped and runs on the way in to the next attempt at the same clip,
    when Resolve has usually let go."""
    d = project_root / 'term'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'A [aaaaaaaaaaa].original.webm').write_bytes(b'x' * 11)
    (d / 'B [bbbbbbbbbbb].original.webm').write_bytes(b'y')
    (d / 'A [aaaaaaaaaaa].mp4').write_bytes(b'z')

    deleted, remaining = worker._retry_aside_originals(d, 'aaaaaaaaaaa')
    assert (deleted, remaining) == (1, 0)
    # the neighbour's is untouched: the folder is shared with the rest of the
    # search and with the other executor
    assert sorted(p.name for p in d.iterdir()) == [
        'A [aaaaaaaaaaa].mp4', 'B [bbbbbbbbbbb].original.webm']


def test_an_original_that_is_still_in_use_is_reported_not_forced(project_root,
                                                                monkeypatch):
    """The file may be in a timeline this second, so the delete is never
    forced. What cannot be reclaimed is REPORTED, in bytes, and the sentence
    goes on the clip row."""
    d = project_root / 'term'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'A [aaaaaaaaaaa].original.webm').write_bytes(b'x' * 2048)

    def refuse(self, *a, **kw):
        raise OSError('Access is denied')

    monkeypatch.setattr(Path, 'unlink', refuse)
    deleted, remaining = worker._retry_aside_originals(d, 'aaaaaaaaaaa')
    assert (deleted, remaining) == (0, 2048)
    assert 'still in use' in worker.reclaimable_note(remaining)
    assert '2048 bytes' in worker.reclaimable_note(remaining)
    assert '—' not in worker.reclaimable_note(remaining)   # house rule
    assert worker.reclaimable_note(0) is None
    assert '1.5 GB' in worker.reclaimable_note(int(1.5 * 1024 ** 3))


def test_the_sweep_leaves_this_runs_resume_state_alone(project_root):
    """A .part from THIS run is yt-dlp's resume state; deleting it costs the
    download it is halfway through."""
    d = project_root / 'term'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'A [aaaaaaaaaaa].f616.mp4.part').write_bytes(b'x')
    worker._sweep_stale(d)
    assert [p.name for p in d.iterdir()] == ['A [aaaaaaaaaaa].f616.mp4.part']


# ------------------------------------------------------------- the bot check

_BOT_MSG = ("ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you're not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication.")


def test_a_bot_check_while_searching_stops_the_job_and_names_the_escape_hatch(
        con, job, fake_claude, fake_youtube, monkeypatch):
    """YTDL-21 (2026-08-11): a challenged IP is challenged for every term, so
    carrying on burns twenty terms' retry budgets to end `done` with nothing and
    no hint. DEPLOY.md's cookies.txt escape hatch is the only fix and nothing
    ever pointed at it."""
    searched = []

    def bot_checked(query, max_results, period=None):
        searched.append(query)
        raise RuntimeError(_BOT_MSG)

    monkeypatch.setattr(worker.ytsearch, 'search', bot_checked)
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert 'YTDL_COOKIES_FILE' in fresh['error']
    assert len(searched) == 1, 'the other three terms must not be attempted'


def test_a_bot_check_while_enriching_stops_the_job(
        con, job, fake_claude, fake_youtube):
    """Metadata failures arrive as a per-row `error` string, not an exception --
    forty of them read as forty dead videos."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb']},
          meta={'aaaaaaaaaaa': {'error': _BOT_MSG}})
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert 'YTDL_COOKIES_FILE' in fresh['error']


def test_a_bot_check_while_downloading_stops_the_rest_of_the_queue(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    tried = []

    def bot_checked(url, outdir, quality='best', **_kw):
        tried.append(url)
        raise RuntimeError(_BOT_MSG)

    monkeypatch.setattr(worker.downloader, 'download', bot_checked)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert 'YTDL_COOKIES_FILE' in fresh['error']
    assert len(tried) == 1
    # the video that was in flight still carries its own error
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'failed'


def test_an_age_gated_video_is_not_read_as_a_bot_check(
        con, job, fake_claude, fake_youtube):
    """"Sign in to confirm your age" is one dead video. Failing the whole job
    over an age-gated clip would be worse than the bug being fixed."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb']},
          meta={'aaaaaaaaaaa': {'error': 'ERROR: [youtube] x: Sign in to confirm '
                                         'your age. This video may be inappropriate'}})
    worker.run_job(con, job['id'])

    assert db.get_job(con, job['id'])['phase'] == 'ready_for_review'
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['relevance_note'] == 'unavailable'


def test_an_ordinary_yt_dlp_failure_is_still_just_one_dead_video(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root):
    """The bot-check short-circuit must not swallow the normal case."""
    fake_downloader.fail_ids = {'aaaaaaaaaaa'}
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done' and (fresh['dl_done'], fresh['dl_failed']) == (1, 1)


# ------------------------------------------------------------- the chmod contract

def test_the_success_path_widens_every_artifact_for_the_fleet(
        con, job, fake_claude, fake_youtube, fake_downloader, project_root,
        monkeypatch):
    """YTDL-45 (2026-08-11): the container runs `umask 077`, so everything the
    download phase writes is 0600 uid 3000 -- on disk and INVISIBLE over SMB to
    every editor. Nothing asserted the widening, and `_chmod` is a no-op on
    Windows, so a regression would keep all eight suites green.

    Recorded at the call site because flipping `os.name` to reach the posix
    branch makes pathlib hand out PosixPath on Windows; the os.chmod hand-off
    itself is pinned in the test below.
    """
    asked = []
    monkeypatch.setattr(worker, '_chmod', lambda p, m: asked.append((Path(p).name, m)))
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
    assert db.get_job(con, job['id'])['dl_done'] == 2

    modes = dict(asked)
    assert modes[job['term_dir']] == 0o2775, 'setgid dir, so clips land in the group'
    assert modes['manifest.json'] == 0o664
    assert sum(1 for n, _ in asked if n.endswith('.mp4')) == 2
    assert sum(1 for n, _ in asked if n.endswith('.credits.json')) == 2
    for name, mode in asked:
        assert mode == (0o2775 if name == job['term_dir'] else 0o664), name


def test_chmod_asks_the_os_for_the_mode_and_never_raises(tmp_path, monkeypatch):
    """The other half of YTDL-45: _chmod really calls os.chmod (off Windows),
    and a filesystem that refuses is a warning, not a failed download."""
    target = tmp_path / 'clip.mp4'
    target.write_bytes(b'x')
    calls = []
    monkeypatch.setattr(worker.os, 'name', 'posix')
    monkeypatch.setattr(worker.os, 'chmod', lambda p, m: calls.append((str(p), m)))
    worker._chmod(target, 0o664)
    assert calls == [(str(target), 0o664)]

    def refuse(_p, _m):
        raise OSError('read-only filesystem')

    monkeypatch.setattr(worker.os, 'chmod', refuse)
    worker._chmod(target, 0o664)


# ------------------------------------------------------------- the worker loop

# The SystemExit below is how the test stops a loop that never returns; pytest
# reports any exception out of a thread, and this one is deliberate.
@pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
def test_a_database_locked_at_boot_does_not_kill_the_worker_thread(con, monkeypatch):
    """YTDL-19 (2026-08-11): the connection was opened outside the loop's try,
    so one transient locked-at-boot raise ended the thread for the life of the
    container -- ensure_started runs only at mount, and the only symptom is a
    `worker_alive:false` nothing reads."""
    attempts = []
    ticks = []

    def flaky_con():
        attempts.append(1)
        if len(attempts) == 1:
            raise sqlite3.OperationalError('database is locked')
        return con

    def tick(c):
        ticks.append(c)
        raise SystemExit    # the only way out of a loop that never returns

    monkeypatch.setattr(worker.db, 'con', flaky_con)
    monkeypatch.setattr(worker, '_tick', tick)
    monkeypatch.setattr(worker, 'IDLE_WAIT', 0.01)
    monkeypatch.setattr(worker.claude_cli, 'refresh_health', lambda force=False: None)

    t = threading.Thread(target=worker._run, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive(), 'the loop never reached a tick'
    assert len(attempts) >= 2, 'the connection was never re-acquired'
    assert ticks == [con]


# ------------------------------------------- the AI health cache heals itself
# ytdl-web-4 (2026-08-21): the boot probe was the only probe anything ever ran,
# and the worker starts at MOUNT time -- on a NAS reboot, routinely before the
# uplink is up. A boot-time failure then pinned the red pip on every editor's
# page until somebody ignored the warning and submitted a job.

def _cache(state, age):
    return lambda: {'claude': state, 'checked_at': time.time() - age,
                    'detail': '', 'provider': ''}


def test_a_red_health_cache_is_probed_again_once_the_worker_is_idle(monkeypatch):
    probes = []
    monkeypatch.setattr(worker.claude_cli, 'health',
                        _cache('missing', worker.UNHEALTHY_RECHECK + 1))
    monkeypatch.setattr(worker.claude_cli, 'refresh_health',
                        lambda force=False: probes.append(force) or
                        {'claude': 'ok', 'provider': 'anthropic_api'})
    assert worker.recheck_health() is True
    assert probes == [False], 'the re-probe must respect _MIN_PROBE_INTERVAL'


def test_a_green_cache_is_never_re_probed(monkeypatch):
    """A probe is a real (tiny) billed call, and on a site with the CLI
    providers on it can be a slow one. Nothing is wrong: do not spend it."""
    probes = []
    monkeypatch.setattr(worker.claude_cli, 'health', _cache('ok', 99999))
    monkeypatch.setattr(worker.claude_cli, 'refresh_health',
                        lambda force=False: probes.append(force))
    assert worker.recheck_health() is False
    assert probes == []


def test_a_wedged_provider_is_not_probed_once_per_idle_tick(monkeypatch):
    """IDLE_WAIT is 5 s. UNHEALTHY_RECHECK is what keeps an hour of downtime
    from becoming 720 probes."""
    probes = []
    monkeypatch.setattr(worker.claude_cli, 'health',
                        _cache('unauthenticated', worker.UNHEALTHY_RECHECK - 30))
    monkeypatch.setattr(worker.claude_cli, 'refresh_health',
                        lambda force=False: probes.append(force))
    assert worker.recheck_health() is False
    assert probes == []


def test_a_failing_probe_never_kills_the_worker(monkeypatch):
    def boom(force=False):
        raise RuntimeError('the network went away mid-probe')

    monkeypatch.setattr(worker.claude_cli, 'health', _cache('error', 99999))
    monkeypatch.setattr(worker.claude_cli, 'refresh_health', boom)
    assert worker.recheck_health() is False


def test_the_idle_loop_is_what_asks_for_the_re_probe(con, monkeypatch):
    """The seam matters as much as the function: nothing else in the tree calls
    refresh_health, so a helper nobody invokes would fix nothing."""
    asked = []

    def probe():
        asked.append(1)
        raise SystemExit    # the only way out of a loop that never returns

    monkeypatch.setattr(worker.db, 'con', lambda: con)
    monkeypatch.setattr(worker, '_boot_recovery', lambda c: None)
    monkeypatch.setattr(worker, '_tick', lambda c: False)
    monkeypatch.setattr(worker, 'IDLE_WAIT', 0.01)
    monkeypatch.setattr(worker.claude_cli, 'refresh_health', lambda force=False: None)
    monkeypatch.setattr(worker, 'recheck_health', probe)

    # In THIS thread, unlike the re-acquire test above: everything the loop
    # touches is patched, and a SystemExit raised on a daemon thread is
    # swallowed by threading.excepthook rather than failing the test.
    with pytest.raises(SystemExit):
        worker._run()
    assert asked == [1]


def test_ensure_started_is_disabled_by_the_test_guard():
    """YTDL_WORKER=0 is what keeps a daemon thread out of this suite (and out
    of the dashboard's mount tests, which import a fake ytdlweb)."""
    assert worker.ensure_started() is False
    assert worker.is_alive() is False


def test_run_job_never_raises_out_of_a_broken_phase(con, job, monkeypatch, fake_claude):
    """One bad job must not cost the fleet its worker thread."""
    def boom(*_a, **_k):
        raise RuntimeError('kaboom')

    monkeypatch.setattr(worker, '_phase_generate_terms', boom)
    worker.run_job(con, job['id'])
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed' and 'kaboom' in fresh['error']


# --- the search phase paces too (2026-08-11, the second block of the day) ----

def test_the_search_phase_waits_between_terms(con, job, fake_claude,
                                              fake_youtube, monkeypatch):
    """Enrichment was paced and the candidate ceiling was in force, and a full
    search STILL bot-checked while a pasted link downloaded fine -- because
    this loop fired one flat search per term back to back, ~24 requests in a
    couple of seconds, and a paste is one request. The pause goes BEFORE each
    search after the first: pausing after the last would only slow a cancel.
    """
    slept = []
    monkeypatch.setattr(worker, '_sleep', slept.append)
    monkeypatch.setattr(worker.config, 'SEARCH_PAUSE', 2.0)
    _wire(fake_youtube, {t['q']: ['aaaaaaaaaaa'] for t in fake_claude.terms})

    worker.run_job(con, job['id'])

    # Counted from what the fake was actually asked, not from the canned term
    # list: the gaps go BETWEEN searches, so the count has to follow the real
    # number of searches however the job got its terms.
    searched = len(fake_youtube.searched)
    assert searched > 1, 'this test needs more than one search to have gaps'
    assert len(slept) == searched - 1, (
        f'{searched} searches want {searched - 1} gaps, got {len(slept)}')
    assert set(slept) == {2.0}


def test_pacing_off_means_no_waiting_at_all(con, job, fake_claude,
                                            fake_youtube, monkeypatch):
    """0 is a supported setting, not a 0-second sleep per term: the sleeper is
    never called, so nothing has to be patched out in a hurry on a host that
    wants the old behaviour back."""
    slept = []
    monkeypatch.setattr(worker, '_sleep', slept.append)
    monkeypatch.setattr(worker.config, 'SEARCH_PAUSE', 0)
    _wire(fake_youtube, {t: ['aaaaaaaaaaa'] for t in (x['q'] for x in fake_claude.terms)})

    worker.run_job(con, job['id'])

    assert slept == []


def test_a_cancel_during_the_search_pause_is_honoured(con, job, fake_claude,
                                                      fake_youtube, monkeypatch):
    """A 24-term job now spends ~48 s in this loop. An editor who pressed
    CANCEL must not wait it out, so cancellation is re-checked on the way out
    of every sleep."""
    monkeypatch.setattr(worker.config, 'SEARCH_PAUSE', 2.0)
    _wire(fake_youtube, {t: ['aaaaaaaaaaa'] for t in (x['q'] for x in fake_claude.terms)})

    def cancel_mid_pause(_seconds):
        db.request_cancel(con, job['id'])

    monkeypatch.setattr(worker, '_sleep', cancel_mid_pause)
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'cancelled'
    # the first term was searched; the second was abandoned in its pause
    assert fresh['terms_done'] == 1


# -------------------------------------------------------- the term scope
# 2026-08-25. Like the mode, it is read off the JOB ROW at every phase.


def test_the_jobs_scope_reaches_both_ai_calls(con, job, fake_claude, fake_youtube):
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    mine = db.create_job(con, USER, 'algal reef controversy', 'algal reef',
                         slug, label, term_scope='zh', auto_terms=True)
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, mine)
    assert fake_claude.scopes == [('terms', 'zh'), ('relevance', 'zh')]
    assert db.get_job(con, mine)['phase'] == 'ready_for_review'


def test_an_old_job_row_is_re_run_as_a_both_languages_search(
        con, job, fake_claude, fake_youtube):
    assert db.get_job(con, job['id'])['term_scope'] == claude_cli.SCOPE_BOTH
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, job['id'])
    assert [s for _stage, s in fake_claude.scopes] == ['both', 'both']


def test_an_exact_search_never_asks_claude_for_terms_and_gets_the_whole_ceiling(
        con, job, fake_claude, fake_youtube):
    """'single search term only': the editor's text is the ONE term, no model
    call expands it, and that one flat search is given the candidate ceiling
    rather than the 15-per-term the expanded search paces itself with. The
    relevance pass still runs -- it judges the topic, not the queries."""
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    mine = db.create_job(con, USER, 'algal reef controversy', 'algal reef',
                         slug, label, max_per_term=5, max_candidates=50,
                         term_scope='exact', auto_terms=True)
    fake_claude.term_error = claude_cli.ClaudeError(
        claude_cli.ERR_AUTH, 'must never be reached')
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa', 'bbbbbbbbbbb']})
    worker.run_job(con, mine)

    fresh = db.get_job(con, mine)
    assert fresh['phase'] == 'ready_for_review', fresh['error']
    assert [c[0] for c in fake_claude.calls] == ['relevance']
    assert fake_claude.scopes == [('relevance', 'exact')]
    terms = db.terms(con, mine)
    assert [(t['term'], t['source']) for t in terms] == \
        [('algal reef controversy', 'user')]
    assert fresh['terms_total'] == 1 and fresh['terms_done'] == 1
    assert fake_youtube.searched == [('algal reef controversy', 50, None)]
    assert fresh['candidates'] == 2


def test_an_exact_search_runs_with_the_ai_provider_down_for_terms(
        con, job, fake_claude, fake_youtube):
    """The one search that needs no model to START. The relevance pass still
    degrades the way it always has (banner, unfiltered manifest)."""
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    mine = db.create_job(con, USER, 'reef', 'reef', slug, label,
                         term_scope='exact', auto_terms=True)
    fake_claude.term_error = claude_cli.ClaudeError(claude_cli.ERR_AUTH, 'logged out')
    fake_claude.relevance_error = claude_cli.ClaudeError(claude_cli.ERR_AUTH, 'logged out')
    _wire(fake_youtube, {'reef': ['aaaaaaaaaaa']})
    worker.run_job(con, mine)
    fresh = db.get_job(con, mine)
    assert fresh['phase'] == 'ready_for_review'
    assert fresh['error'] and fresh['error'].startswith(claude_cli.ERR_AUTH)
    assert [v['video_id'] for v in db.videos(con, mine)] == ['aaaaaaaaaaa']


def test_a_single_language_scope_still_searches_the_editors_own_term_first(
        con, job, fake_claude, fake_youtube):
    """The editor typed it, whatever language it is in: a chinese term under
    ENGLISH ONLY is still the first search (source='user')."""
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    mine = db.create_job(con, USER, '藻礁', '藻礁', slug, label,
                         term_scope='en', auto_terms=True)
    _wire(fake_youtube, {'藻礁': ['aaaaaaaaaaa']})
    worker.run_job(con, mine)
    terms = db.terms(con, mine)
    assert (terms[0]['term'], terms[0]['lang'], terms[0]['source']) == ('藻礁', 'zh', 'user')
    assert fake_youtube.searched[0][0] == '藻礁'


# --------------------------------------------------------- the date range
# YouTube's search has no range filter, so the range is enforced on each
# candidate's metadata in the filter phase -- a soft drop like the live and
# over-length ones, and a card the editor can still overrule.


def _dated_job(con, job, **over):
    slug, label, _ = PROJECTS[1]
    db.set_phase(con, job['id'], 'cancelled')
    over.setdefault('auto_terms', True)
    return db.create_job(con, USER, 'reef', 'reef', slug, label, **over)


def test_candidates_outside_the_upload_date_range_are_dropped_mechanically(
        con, job, fake_claude, fake_youtube):
    mine = _dated_job(con, job, date_from='20190101', date_to='20191231')
    _wire(fake_youtube, {'reef': ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc',
                                  'ddddddddddd', 'eeeeeeeeeee']},
          meta={'aaaaaaaaaaa': {'upload_date': '20190615'},   # inside
                'bbbbbbbbbbb': {'upload_date': '20181231'},   # the day before
                'ccccccccccc': {'upload_date': '20200101'},   # the day after
                'ddddddddddd': {'upload_date': '20191231'},   # the last day: inside
                'eeeeeeeeeee': {'upload_date': None}})        # unknown: kept
    worker.run_job(con, mine)
    rows = {v['video_id']: v for v in db.videos(con, mine)}
    assert rows['aaaaaaaaaaa']['relevant'] == 1
    assert rows['ddddddddddd']['relevant'] == 1
    assert rows['eeeeeeeeeee']['relevant'] == 1, 'no upload_date never drops'
    assert rows['bbbbbbbbbbb']['relevant'] == 0 and rows['bbbbbbbbbbb']['selected'] == 0
    assert rows['ccccccccccc']['relevant'] == 0
    assert rows['bbbbbbbbbbb']['relevance_note'] == \
        'uploaded 2018-12-31, outside 2019-01-01 to 2019-12-31'
    # ...and the judge never saw the dropped ones: no tokens spent on a card
    # the range already decided
    judged = [c[2] for c in fake_claude.calls if c[0] == 'relevance'][0]
    assert set(judged) == {'aaaaaaaaaaa', 'ddddddddddd', 'eeeeeeeeeee'}


def test_a_one_sided_range_binds_one_side(con, job, fake_claude, fake_youtube):
    mine = _dated_job(con, job, date_from='20250101')
    _wire(fake_youtube, {'reef': ['aaaaaaaaaaa', 'bbbbbbbbbbb']},
          meta={'aaaaaaaaaaa': {'upload_date': '20240101'},
                'bbbbbbbbbbb': {'upload_date': '20260801'}})
    worker.run_job(con, mine)
    rows = {v['video_id']: v for v in db.videos(con, mine)}
    assert rows['aaaaaaaaaaa']['relevant'] == 0
    assert rows['aaaaaaaaaaa']['relevance_note'] == \
        'uploaded 2024-01-01, outside 2025-01-01 onwards'
    assert rows['bbbbbbbbbbb']['relevant'] == 1
    assert worker._date_range_text(None, '20250101') == 'up to 2025-01-01'


def test_no_range_drops_nothing_and_the_note_is_the_old_one(
        con, job, fake_claude, fake_youtube):
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']},
          meta={'aaaaaaaaaaa': {'upload_date': '19990101'}})
    worker.run_job(con, job['id'])
    v = db.videos(con, job['id'])[0]
    assert v['relevant'] == 1 and not v['relevance_note']
    assert not worker._outside_dates({'upload_date': '19990101'}, None, None)
    # a malformed bound (a row written by hand) is no bound, never a crash
    assert not worker._outside_dates({'upload_date': '19990101'}, 'soon', None)
    assert not worker._outside_dates({'upload_date': 'junk'}, '20200101', None)


# ============================================================================
# WP3: anonymous first, the cookie jar as the fallback (plan WP3, 2026-08-26)
#
# CR-80: the jar was passed on EVERY call, so one flagged YouTube account was
# fatal to every download the server could make and there was no second path to
# fall back to. These tests pin the inversion, both fallbacks, the sticky
# preference and the state where neither path is left.
# ============================================================================

from ytdlweb import ytdl_evidence                                # noqa: E402

_FLAG_MSG = 'ERROR: [youtube] dQw4w9WgXcQ: The page needs to be reloaded.'


@pytest.fixture(autouse=True)
def fresh_paths():
    """Nothing in this module inherits another test's path verdict.

    Both are module-level in the worker on purpose (a job must not re-discover
    the working path per clip), which makes them exactly the kind of state a
    suite has to reset between tests.
    """
    ytdl_evidence.reset()
    worker.reset_preferred_path()
    yield
    ytdl_evidence.reset()
    worker.reset_preferred_path()


def _jar(tmp_path, monkeypatch, present=True):
    """A configured cookies.txt, holding a session or only its header.

    The header-only shape is CR-80's parked state: YTDL_COOKIES_FILE stays set
    so yt-dlp keeps writing its own anonymous cookies somewhere, and there is
    no signed-in session to fall back to.
    """
    p = tmp_path / 'cookies.txt'
    body = '# Netscape HTTP Cookie File\n# comment\n'
    if present:
        body += '.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc123\n'
    p.write_text(body, encoding='utf-8')
    monkeypatch.setattr(config, 'COOKIES_FILE', str(p))
    return p


class PathAwareDownloader:
    """A downloader that records WHICH path each attempt took.

    `fail(vid, quality, path)` returns an exception to raise, or None. Real
    files on the success path, for the same reason FakeDownloader writes them:
    the dedupe re-check greps the folder for `[id]` names.
    """

    def __init__(self, fail=None):
        self.fail = fail or (lambda vid, quality, path: None)
        self.calls = []            # [(video_id, quality, path), ...]

    def download(self, url, outdir, quality='best', cookies_file=None, **_kw):
        vid = url.rsplit('=', 1)[-1]
        path = (ytdl_evidence.PATH_COOKIES if cookies_file
                else ytdl_evidence.PATH_ANONYMOUS)
        self.calls.append((vid, quality, path))
        exc = self.fail(vid, quality, path)
        if exc is not None:
            raise exc
        p = Path(outdir) / f'Test Channel - {vid} title [{vid}].mp4'
        p.write_bytes(b'fake video')
        side = p.with_suffix('.credits.json')
        side.write_text('{}', encoding='utf-8')
        return {'title': f'{vid} title', 'channel': 'Test Channel',
                'video_url': url, 'thumbnail': None, 'duration': 120,
                'filepath': str(p), 'sidecar': str(side)}


def _paths(fake):
    return [c[2] for c in fake.calls]


def test_a_download_is_anonymous_even_with_a_working_jar_configured(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, tmp_path):
    """The inversion itself: a configured, usable jar is the ESCAPE HATCH, not
    the default (CR-80). Until 2026-08-26 this call carried the cookies."""
    _jar(tmp_path, monkeypatch)
    fake = PathAwareDownloader()
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert _paths(fake) == [ytdl_evidence.PATH_ANONYMOUS]
    assert db.get_job(con, job['id'])['phase'] == 'done'
    assert worker.preferred_path() == ytdl_evidence.PATH_ANONYMOUS
    # ...and the attempt is EVIDENCE, which is what health reads (WP5)
    snap = ytdl_evidence.snapshot()
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['ok'] is True
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['video_id'] == 'aaaaaaaaaaa'


def test_a_bot_check_falls_back_to_the_jar_and_the_preference_sticks(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, tmp_path):
    """A challenged IP is what the jar is FOR. And once it has worked, the next
    clip starts there: a job must not re-discover the same wall per clip."""
    _jar(tmp_path, monkeypatch)

    def fail(vid, quality, path):
        if path == ytdl_evidence.PATH_ANONYMOUS:
            return RuntimeError(_BOT_MSG)
        return None

    fake = PathAwareDownloader(fail)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])

    assert _paths(fake) == [ytdl_evidence.PATH_ANONYMOUS,
                            ytdl_evidence.PATH_COOKIES,
                            ytdl_evidence.PATH_COOKIES]
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done' and (fresh['dl_done'], fresh['dl_failed']) == (2, 0)
    assert worker.preferred_path() == ytdl_evidence.PATH_COOKIES
    snap = ytdl_evidence.snapshot()
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['ok'] is False
    assert snap[ytdl_evidence.PATH_COOKIES]['ok'] is True


def test_a_flagged_session_falls_back_to_anonymous_and_is_not_fatal(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, tmp_path):
    """CR-80 in one test: the cookies path is refused, anonymous works, and the
    job finishes. The old code had no path that did not carry the jar."""
    _jar(tmp_path, monkeypatch)
    worker.set_preferred_path(ytdl_evidence.PATH_COOKIES)

    def fail(vid, quality, path):
        if path == ytdl_evidence.PATH_COOKIES:
            return RuntimeError(_FLAG_MSG)
        return None

    fake = PathAwareDownloader(fail)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert _paths(fake) == [ytdl_evidence.PATH_COOKIES,
                            ytdl_evidence.PATH_ANONYMOUS]
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done' and fresh['dl_done'] == 1
    assert worker.preferred_path() == ytdl_evidence.PATH_ANONYMOUS


def test_both_paths_blocked_stops_the_phase_and_names_both_symptoms(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, tmp_path):
    """The state CR-80 would have been if the IP had also been challenged: no
    retry gets out of it, and the note has to say what to export and how to
    test it, because "downloads are failing" names neither."""
    _jar(tmp_path, monkeypatch)

    def fail(vid, quality, path):
        return RuntimeError(_BOT_MSG if path == ytdl_evidence.PATH_ANONYMOUS
                            else _FLAG_MSG)

    fake = PathAwareDownloader(fail)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])

    assert _paths(fake) == [ytdl_evidence.PATH_ANONYMOUS,
                            ytdl_evidence.PATH_COOKIES], 'the queue stopped'
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    note = fresh['error']
    assert 'not a bot' in note and 'page needs to be reloaded' in note
    assert 'FRESH cookies.txt' in note and 'DEPLOY.md' in note
    assert '—' not in note
    # the clip that was in flight still carries its own error
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'failed'
    assert db.get_video(con, job['id'], 'bbbbbbbbbbb')['dl_state'] == 'pending'


def test_the_blocked_both_ways_error_is_handled_by_the_bot_check_handler():
    """Subclassed so run_job's existing `except BotCheckError` covers it: both
    mean "this repeats for every remaining clip", only the note differs."""
    assert issubclass(worker.DownloadPathsBlockedError, worker.BotCheckError)


def test_a_header_only_jar_is_not_a_path_to_fall_back_to(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, tmp_path):
    """CR-80 parked the flagged jar as its two Netscape header lines with
    YTDL_COOKIES_FILE still set. "A path is configured" is not a session, and
    attempting it would spend an extraction to learn nothing."""
    _jar(tmp_path, monkeypatch, present=False)
    fake = PathAwareDownloader(lambda vid, q, path: RuntimeError(_BOT_MSG))
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])

    assert _paths(fake) == [ytdl_evidence.PATH_ANONYMOUS]
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert 'YTDL_COOKIES_FILE' in fresh['error']
    assert not worker.cookies_available()


def test_a_transient_failure_never_spends_the_credential(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, tmp_path):
    """403s, dead networks and missing formats are not path-specific: they fail
    the same way with an account, and switching would burn the escape hatch on
    a failure it cannot fix."""
    _jar(tmp_path, monkeypatch)
    fake = PathAwareDownloader(
        lambda vid, q, path: RuntimeError('ERROR: unable to download video '
                                          'data: HTTP Error 403: Forbidden'))
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert _paths(fake) == [ytdl_evidence.PATH_ANONYMOUS]
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'failed'
    assert worker.preferred_path() == ytdl_evidence.PATH_ANONYMOUS


def test_the_truncation_retry_still_composes_with_path_selection(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch, tmp_path):
    """The 2026-08-13 fallback and the 2026-08-26 inversion in one clip: 1080p
    ends short, the 720p rung is bot-checked anonymously, and the jar lands it.
    The row must still say the quality it actually got."""
    _jar(tmp_path, monkeypatch)

    def fail(vid, quality, path):
        if quality == '1080p':
            return DownloadError(_TRUNCATED)
        if path == ytdl_evidence.PATH_ANONYMOUS:
            return RuntimeError(_BOT_MSG)
        return None

    fake = PathAwareDownloader(fail)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    assert fake.calls == [
        ('aaaaaaaaaaa', '1080p', ytdl_evidence.PATH_ANONYMOUS),
        ('aaaaaaaaaaa', '720p', ytdl_evidence.PATH_ANONYMOUS),
        ('aaaaaaaaaaa', '720p', ytdl_evidence.PATH_COOKIES)]
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'done'
    assert v['dl_error'] == '1080p stream truncated by YouTube, fell back to 720p'


def test_a_bot_check_on_the_lower_rung_is_not_dressed_up_as_a_quality_failure(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """With no jar the phase is over, and the note has to be the one naming the
    escape hatch, not "the 720p retry failed too", which names no fix."""
    monkeypatch.setattr(config, 'COOKIES_FILE', '')

    def fail(vid, quality, path):
        return (DownloadError(_TRUNCATED) if quality == '1080p'
                else RuntimeError(_BOT_MSG))

    fake = PathAwareDownloader(fail)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert 'YTDL_COOKIES_FILE' in fresh['error']


# ============================================================================
# WP4 + WP6: one job must not discover the same wall 29 times (2026-08-26)
# ============================================================================

def _same_wall(msg):
    """A per-clip failure that differs only by video id, like YouTube's do."""
    return lambda vid, q, path: RuntimeError(f'ERROR: [youtube] {vid}: {msg}')


_NO_FORMAT = 'Requested format is not available. Use --list-formats'


def test_the_same_failure_three_times_stops_the_phase(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """CR-80's job 28 failed 29 rows with one opaque string, ten yt-dlp retries
    each. The rows it never reached stay `pending`, which is what makes the
    retry a one-liner."""
    fake = PathAwareDownloader(_same_wall(_NO_FORMAT))
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    monkeypatch.setattr(worker, 'MAX_IDENTICAL_FAILURES', 3)
    _download(con, job, fake_claude, fake_youtube,
              ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc', 'ddddddddddd'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'failed'
    assert len(fake.calls) == 3, 'the fourth clip was never attempted'
    states = {v['video_id']: v['dl_state'] for v in db.videos(con, job['id'])}
    assert states['ddddddddddd'] == 'pending'
    assert states['ccccccccccc'] == 'failed'
    # the rows keep their own error, as they always have
    assert 'Requested format' in db.get_video(con, job['id'],
                                              'aaaaaaaaaaa')['dl_error']
    # ...and the manifest still describes what the run did (batch_dl.py and the
    # companion both read it)
    assert (project_root / job['term_dir'] / 'manifest.json').exists()

    note = fresh['error']
    assert '3 clips in a row' in note and 'yt-dlp' in note
    assert '—' not in note


def test_two_identical_failures_are_not_a_wall(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """N-1 is an ordinary afternoon on YouTube: the job finishes `done` with
    two visible per-row failures, exactly as it always did."""
    fake = PathAwareDownloader(_same_wall(_NO_FORMAT))
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    monkeypatch.setattr(worker, 'MAX_IDENTICAL_FAILURES', 3)
    _download(con, job, fake_claude, fake_youtube, ['aaaaaaaaaaa', 'bbbbbbbbbbb'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done' and fresh['dl_failed'] == 2


def test_a_clip_that_lands_resets_the_breaker(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """CONSECUTIVE is the whole rule: four scattered failures around one good
    clip is not a wall, and parking the job would lose the rest of the queue."""
    def fail(vid, quality, path):
        if vid == 'ccccccccccc':
            return None
        return RuntimeError(f'ERROR: [youtube] {vid}: {_NO_FORMAT}')

    fake = PathAwareDownloader(fail)
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    monkeypatch.setattr(worker, 'MAX_IDENTICAL_FAILURES', 3)
    _download(con, job, fake_claude, fake_youtube,
              ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc', 'ddddddddddd',
               'eeeeeeeeeee'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done'
    assert (fresh['dl_done'], fresh['dl_failed']) == (1, 4)
    assert len(fake.calls) == 5


def test_two_different_failures_do_not_add_up(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """The breaker counts THE SAME wall, not failures: three unrelated dead
    clips are three dead clips."""
    msgs = {'aaaaaaaaaaa': 'Private video', 'bbbbbbbbbbb': _NO_FORMAT,
            'ccccccccccc': 'HTTP Error 403: Forbidden'}
    fake = PathAwareDownloader(
        lambda vid, q, path: RuntimeError(f'ERROR: [youtube] {vid}: {msgs[vid]}'))
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    monkeypatch.setattr(worker, 'MAX_IDENTICAL_FAILURES', 3)
    _download(con, job, fake_claude, fake_youtube,
              ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'])

    assert db.get_job(con, job['id'])['phase'] == 'done'
    assert len(fake.calls) == 3


def test_the_breaker_can_be_turned_off_without_a_build(
        con, job, fake_claude, fake_youtube, project_root, monkeypatch):
    """YTDL_MAX_IDENTICAL_FAILURES=0 is the escape hatch for a false positive:
    grind through the queue the way it always did."""
    fake = PathAwareDownloader(_same_wall(_NO_FORMAT))
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    monkeypatch.setattr(worker, 'MAX_IDENTICAL_FAILURES', 0)
    _download(con, job, fake_claude, fake_youtube,
              ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc', 'ddddddddddd'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done' and fresh['dl_failed'] == 4
    assert len(fake.calls) == 4


def test_a_failure_signature_ignores_the_video_id_and_the_numbers():
    """What makes "the same wall on a different clip" the same key."""
    sig = worker._failure_signature
    assert sig('ERROR: [youtube] SAQBbd1Rxmo: Requested format is not available') \
        == sig('ERROR: [youtube] dQw4w9WgXcQ: Requested format is not available')
    assert sig('[Errno 13] Permission denied: /tmp/a1b2c3.tmp') \
        == sig('[Errno 13] Permission denied: /tmp/z9y8x7.tmp')
    assert sig('Requested format is not available') != sig('HTTP Error 403')
    assert len(sig('x' * 400)) <= 120


@pytest.mark.parametrize('error,expected', [
    (f'ERROR: [youtube] x: {_NO_FORMAT}', 'no usable format'),
    ('ERROR: unable to download video data: HTTP Error 403: Forbidden',
     'YTDL_POT_BASE_URL'),
    ('ERROR: something nobody has classified yet', 'failed the same way'),
])
def test_the_phase_note_names_the_thing_to_check(error, expected):
    """Three walls, three remedies. An editor cannot tell a SABR squeeze from a
    dead PO-token sidecar from a raw stderr dump, so the note has to."""
    note = worker.identical_failure_note(4, error)
    assert expected in note
    assert note.startswith('4 clips in a row')
    assert '—' not in note
    assert 'RETRY' in note
