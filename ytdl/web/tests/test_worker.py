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
import threading
import time
from pathlib import Path

import pytest

from tests.conftest import PROJECTS, USER
from ytdlweb import claude_cli, db, worker
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


# ---------------------------------------------------------------- the sweep

def test_the_sweep_takes_fragments_and_leaves_the_deliverables(project_root):
    """YTDL-17 (2026-08-11): `'.part' in name` also matched a title containing
    ".part", and `.editready` matched `<stem>.editready.mp4` -- which is not a
    leftover but _swap_in's fallback DELIVERABLE, ledgered under exactly that
    name. Sweeping it left the ledger blocking a fleet-wide re-fetch and any
    Resolve project referencing it Media Offline."""
    d = project_root / 'term'
    d.mkdir(parents=True, exist_ok=True)
    swept = ['A [aaaaaaaaaaa].f616.mp4.part', 'A [aaaaaaaaaaa].f616.mp4.ytdl',
             'A [aaaaaaaaaaa].part-Frag7']
    kept = ['A [aaaaaaaaaaa].editready.mp4', 'A [bbbbbbbbbbb].mp4',
            'The .part standard explained [ccccccccccc].mp4', 'manifest.json']
    for name in swept + kept:
        p = d / name
        p.write_bytes(b'x')
        old = time.time() - worker.STALE_AFTER - 60
        os.utime(p, (old, old))

    worker._sweep_stale(d)
    assert sorted(p.name for p in d.iterdir()) == sorted(kept)


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
