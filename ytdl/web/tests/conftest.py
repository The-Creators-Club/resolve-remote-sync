"""Fixtures for the ytdl web app.

`ytdlweb.config` reads its paths at import time, so every one of them is
pointed at a throwaway tree BEFORE anything imports the package -- including
YTDL_PROJECTS_ROOT, because the dedupe scan and the download phase both write
into it and a test that reached the real /projects would be a very bad day.

**YTDL_WORKER=0 is set here and must stay set.** The pipeline worker is a
daemon thread that claims any non-terminal job it finds; started by a fixture
it would race every test in this suite for the same rows. Everything that
exercises the pipeline calls `worker.run_job()` directly instead, which is
synchronous and takes the connection it should use.

Nothing here needs yt-dlp or the claude CLI: both are reached through seams the
tests replace (`ytdlweb.vendor.ytsearch` / `ytdlweb.claude_cli`), which is the
same property that lets the app mount on a host that has neither.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = Path(tempfile.mkdtemp(prefix='ytdlweb-tests-'))
_DATA = _TMP / 'data'
_PROJECTS = _TMP / 'projects'
_DASH_DB = _TMP / 'dashboard.db'
_DATA.mkdir(parents=True, exist_ok=True)
_PROJECTS.mkdir(parents=True, exist_ok=True)

os.environ['YTDL_WORKER'] = '0'
os.environ['YTDL_DATA_ROOT'] = str(_DATA)
os.environ['YTDL_PROJECTS_ROOT'] = str(_PROJECTS)
os.environ['YTDL_DASH_DB'] = str(_DASH_DB)
os.environ['YTDL_DEV_USER'] = ''
os.environ['YTDL_DOWNLOAD_PAUSE'] = '0'         # the 3 s pacing is not a test
os.environ['YTDL_CLAUDE_HOME'] = str(_TMP / 'claude-home')

from ytdlweb import config, db                   # noqa: E402
from ytdlweb.main import app                     # noqa: E402

USER = 'alex'
OTHER_USER = 'sam'

# The two projects `alex` syncs, and the one `sam` does. Labels are rel paths,
# exactly as the dashboard stores them.
PROJECTS = [
    ('2026-ff5-energy', '2026/FF5/Energy Transition', 1),
    ('2026-ff5-water', '2026/FF5/Water', 2),
]
OTHER_PROJECT = ('2025-ff4-nuclear', '2025/FF4/Nuclear')

# Verbatim from dashboard/src/ccsync_dashboard/schema.sql (projects) and
# db.py's SCHEMA_V2 (selections). Copied rather than imported: this suite must
# run with no dashboard checkout in reach, and a drift between the two is
# exactly what the read-only query in projects.py would break on.
_DASH_DDL = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  path TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS selections (
  editor_username TEXT NOT NULL,
  project_slug    TEXT NOT NULL,
  position        INTEGER NOT NULL,
  created_at      TEXT NOT NULL,
  created_by      TEXT NOT NULL,
  PRIMARY KEY (editor_username, project_slug)
);
"""


def _seed_dashboard_db():
    con = sqlite3.connect(_DASH_DB)
    con.executescript(_DASH_DDL)
    rows = [*PROJECTS, (OTHER_PROJECT[0], OTHER_PROJECT[1], 1)]
    for slug, label, _pos in rows:
        con.execute('INSERT OR IGNORE INTO projects(slug,label,path,first_seen,'
                    'last_seen,active) VALUES(?,?,?,?,?,1)',
                    (slug, label, f'/projects/{label}', '2026-08-11', '2026-08-11'))
    # An inactive project the editor still has a selection row for: it must NOT
    # come back from api/projects, and it must not be a valid destination.
    con.execute("INSERT OR IGNORE INTO projects(slug,label,path,first_seen,last_seen,active) "
                "VALUES('2024-old','2024/Old','/projects/2024/Old','x','x',0)")
    for slug, _label, pos in PROJECTS:
        con.execute('INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?)',
                    (USER, slug, pos, '2026-08-11', 'seed'))
    con.execute('INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?)',
                (USER, '2024-old', 9, '2026-08-11', 'seed'))
    con.execute('INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?)',
                (OTHER_USER, OTHER_PROJECT[0], 1, '2026-08-11', 'seed'))
    con.commit()
    con.close()


@pytest.fixture(scope='session', autouse=True)
def tmp_roots():
    """The throwaway data/projects roots and a fixture dashboard database."""
    _seed_dashboard_db()
    con = db.connect()
    db.init(con)
    con.close()
    return _TMP


@pytest.fixture()
def con(tmp_roots):
    """A fresh connection with an EMPTY schema for each test.

    Wiped rather than re-created: db.con() caches one connection per thread and
    the app's routes go through it, so the file has to stay the same file.
    """
    c = db.con()
    for table in ('job_video_terms', 'job_videos', 'job_terms', 'jobs', 'downloads'):
        c.execute(f'DELETE FROM {table}')
    c.commit()
    return c


@pytest.fixture()
def client(con):
    """The app served at the origin root, as `uvicorn ytdlweb.main:app` does."""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        c.headers.update({'x-ccsync-user': USER})
        yield c


@pytest.fixture()
def job(con):
    """A queued job for USER against their first ticked project."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'algal reef controversy',
                           config.safe_term_dirname('algal reef controversy'),
                           slug, label, quality='1080p', max_per_term=5)
    return db.get_job(con, job_id)


@pytest.fixture(autouse=True)
def clean_projects(tmp_roots):
    """Empty the fake Projects tree before every test.

    Not tidiness: the dedupe reads the DESTINATION FOLDER for `[id]` filenames,
    so a file left behind by an earlier test would make the next one's videos
    duplicates and every download would be skipped.
    """
    shutil.rmtree(_PROJECTS, ignore_errors=True)
    _PROJECTS.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture()
def project_root(clean_projects):
    """<projects>/<label>/Youtube for the fixture job's project."""
    p = _PROJECTS / PROJECTS[0][1] / 'Youtube'
    p.mkdir(parents=True, exist_ok=True)
    return p


class FakeClaude:
    """Stand-in for the `claude -p` seam.

    Records what it was asked and answers from canned data. Everything the
    worker does with Claude goes through the two functions below, so this is
    the whole surface -- there is no path in the pipeline that shells out
    without passing here.
    """

    def __init__(self, terms=None, verdicts=None, term_error=None,
                 relevance_error=None):
        self.terms = terms if terms is not None else [
            {'q': 'algal reef taiwan', 'lang': 'en', 'english_gloss': None},
            {'q': 'lng terminal protest', 'lang': 'en', 'english_gloss': None},
            {'q': '藻礁 三接 爭議', 'lang': 'zh', 'english_gloss': 'algal reef third LNG terminal dispute'},
        ]
        self.verdicts = verdicts or {}
        self.term_error = term_error
        self.relevance_error = relevance_error
        self.calls = []

    def generate_terms(self, topic, timeout=None):
        self.calls.append(('terms', topic))
        if self.term_error:
            raise self.term_error
        return self.terms

    def filter_relevance(self, topic, videos, batch=40, timeout=None):
        self.calls.append(('relevance', topic, [v['id'] for v in videos]))
        if self.relevance_error:
            raise self.relevance_error
        return self.verdicts


@pytest.fixture()
def fake_claude(monkeypatch):
    """Patch the worker's two Claude calls. Health/note_failure stay real."""
    from ytdlweb import claude_cli, worker
    fake = FakeClaude()
    monkeypatch.setattr(worker.claude_cli, 'generate_terms', fake.generate_terms)
    monkeypatch.setattr(worker.claude_cli, 'filter_relevance', fake.filter_relevance)
    monkeypatch.setattr(claude_cli, 'refresh_health', lambda force=False: claude_cli.health())
    return fake


class FakeYouTube:
    """Stand-in for ytdlweb.vendor.ytsearch's network half.

    `results` maps a term to the video ids it returns, so a test can make two
    terms surface the same video (the multi-term attribution case) without
    caring how yt-dlp spells an entry.
    """

    def __init__(self, results=None, meta=None, fail_terms=()):
        self.results = results or {}
        self.meta = meta or {}
        self.fail_terms = set(fail_terms)
        self.searched = []
        self.enriched = []

    def search(self, query, max_results, period=None):
        self.searched.append((query, max_results, period))
        if query in self.fail_terms:
            raise RuntimeError('HTTP 429 from YouTube')
        return [{'id': vid, 'title': f'{vid} title',
                 'url': f'https://www.youtube.com/watch?v={vid}'}
                for vid in self.results.get(query, [])][:max_results]

    def enrich(self, entries, jobs=4, progress=None):
        out = []
        for i, e in enumerate(entries, start=1):
            self.enriched.append(e['id'])
            base = {'id': e['id'], 'url': e['url'], 'title': f"{e['id']} title",
                    'channel': 'Test Channel', 'duration': 120.0,
                    'upload_date': '20260801', 'view_count': 1000,
                    'thumbnail': f"https://i.ytimg.com/vi/{e['id']}/hq.jpg",
                    'is_live': False}
            base.update(self.meta.get(e['id'], {}))
            out.append(base)
            if progress:
                progress(i, len(entries))
        return out


@pytest.fixture()
def fake_youtube(monkeypatch):
    from ytdlweb import worker
    fake = FakeYouTube()
    monkeypatch.setattr(worker.ytsearch, 'search', fake.search)
    monkeypatch.setattr(worker.ytsearch, 'enrich', fake.enrich)
    return fake


class FakeDownloader:
    """Stand-in for vendor.downloader.download -- writes a real file.

    A real file, because the dedupe re-check greps the destination folder for
    `[id]` filenames and a mock that wrote nothing would let a broken dedupe
    pass.
    """

    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.calls = []

    def download(self, url, outdir, quality='best', **kw):
        vid = url.rsplit('=', 1)[-1]
        self.calls.append((vid, outdir, quality))
        if vid in self.fail_ids:
            raise RuntimeError('yt-dlp said no')
        path = Path(outdir) / f'Test Channel - {vid} title [{vid}].mp4'
        path.write_bytes(b'fake video')
        side = path.with_suffix('.credits.json')
        side.write_text('{}', encoding='utf-8')
        return {'title': f'{vid} title', 'channel': 'Test Channel',
                'video_url': url, 'thumbnail': None, 'duration': 120,
                'filepath': str(path), 'sidecar': str(side)}


@pytest.fixture()
def fake_downloader(monkeypatch):
    from ytdlweb import worker
    fake = FakeDownloader()
    monkeypatch.setattr(worker.downloader, 'download', fake.download)
    return fake
