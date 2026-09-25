"""The 2026-09-24 hunt, ytdl/web's half (webapps-ops group).

One section per finding id, so `grep -rn bug-music-ytdl-1 tests/` lands on
the test as well as on the code. Every test here fails on the source before
the fix beside it.
"""
from tests.test_bug_hunt_2026_09_18_webapps_tools import (
    _downloading_url_job, _gone_root)
from tests.conftest import PROJECTS
from ytdlweb import config, db, worker


# ------------------------------------------------------------ bug-music-ytdl-1

def test_the_download_phase_refuses_a_vanished_share_it_would_have_created(
        con, tmp_path, monkeypatch):
    """The guard used to run AFTER `ensure_outdir` had made <root>/<label> on
    the leftover mount point, so `tree_is_gone` saw a folder and said
    "present": the job downloaded into the container overlay. The phase
    itself is driven here, not the helper, because the helper was always
    right and the ORDER was the bug."""
    root = _gone_root(tmp_path, monkeypatch, free_gb=200)
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', False)
    job = _downloading_url_job(con)
    calls = []

    def download(url, outdir, quality='best', **kw):
        calls.append((url, outdir))
        raise RuntimeError('the phase must not reach yt-dlp')
    monkeypatch.setattr(worker.downloader, 'download', download)

    worker._phase_download(con, job)

    after = db.get_job(con, job['id'])
    assert calls == [], f'fetched into the overlay: {calls}'
    assert after['phase'] == 'failed', after['phase']
    assert 'lost the share' in (after['error'] or ''), after['error']
    # Nothing left behind to fool the next press's tree check either.
    assert not (root / PROJECTS[0][1]).exists()
    assert db.pending_videos(con, job['id']), 'rows must stay pending for RETRY'
