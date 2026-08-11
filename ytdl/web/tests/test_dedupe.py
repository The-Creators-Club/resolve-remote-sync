"""REQ 6: a clip the fleet already has is flagged and never fetched again.

The dedupe has two sources and neither is complete on its own:

  the `downloads` ledger  knows about downloads into OTHER projects, which no
                          filesystem scan of THIS project could ever see;
  the filesystem          knows about clips that predate the ledger, that an
                          editor copied in by hand, or that landed from a job
                          whose database row was lost.

So they are unioned, and the union is re-checked immediately before the
bandwidth is spent -- tested here and in test_worker.py's download cases.
"""
import pytest

from tests.conftest import PROJECTS, USER
from ytdlweb import config, db, worker
from ytdlweb.vendor import ytsearch


def _touch(dirpath, name):
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / name
    p.write_bytes(b'x')
    return p


def test_existing_ids_reads_the_id_out_of_the_filename(project_root):
    _touch(project_root / 'old term', 'Channel - Some Title [abcdefghijk].mp4')
    _touch(project_root / 'old term', 'Channel - Some Title [abcdefghijk].credits.json')
    _touch(project_root / 'old term', 'no id here.mp4')
    assert ytsearch.existing_ids(project_root) == {'abcdefghijk'}
    # the folder is what the ALREADY IN badge names
    assert ytsearch.existing_id_locations(project_root)['abcdefghijk'] == 'old term'


def test_existing_ids_on_a_missing_folder_is_empty_not_an_error(tmp_path):
    """A project that has never had a Youtube folder is the normal first case."""
    assert ytsearch.existing_ids(tmp_path / 'nope') == set()


def test_an_interrupted_downloads_leftovers_are_not_a_clip(project_root):
    """YTDL-2 (2026-08-11): a container restart mid-download leaves yt-dlp's
    fragments behind, and boot recovery re-queues the video. When the .part
    counted as "the fleet already has it" the video was marked duplicate, the
    resume never happened, and the sweep deleted the fragment a day later --
    leaving nothing at all."""
    d = project_root / 'in flight'
    for name in ('Chan - T [abcdefghijk].f616.mp4.part',
                 'Chan - T [abcdefghijk].f616.mp4.ytdl',
                 'Chan - T [abcdefghijk].f251.webm',
                 'Chan - T [abcdefghijk].part',
                 'Chan - T [abcdefghijk].part-Frag12',
                 'Chan - T [abcdefghijk].editready.mp4',
                 'Chan - T [abcdefghijk].mp4.failed'):
        _touch(d, name)
    assert ytsearch.existing_ids(project_root) == set()

    # ...and the moment the real file lands, it counts.
    _touch(d, 'Chan - T [abcdefghijk].mp4')
    assert ytsearch.existing_ids(project_root) == {'abcdefghijk'}


def test_the_id_is_taken_from_the_end_of_the_name_not_the_first_bracket(project_root):
    """YTDL-27 (2026-08-11): the outtmpl puts `[id]` last, but a title can carry
    its own bracketed 11-character token. Registering that one instead loses the
    real id, so the clip is invisible to the disk scan and re-downloaded."""
    _touch(project_root / 'music', 'Chan - Song [OFFICIAL_MV] [dQw4w9WgXcQ].mp4')
    assert ytsearch.existing_ids(project_root) == {'dQw4w9WgXcQ'}


def test_a_clip_downloaded_into_another_project_is_flagged(con, job):
    db.add_video(con, job['id'], 'abcdefghijk', 'u')
    db.ledger_add(con, 'abcdefghijk', 't', 'c', '2025-ff4-nuclear',
                  '2025/FF4/Nuclear', 'nuclear protest',
                  'Youtube/nuclear protest/x.mp4')

    assert worker.mark_duplicates(con, job) == 1
    v = db.get_video(con, job['id'], 'abcdefghijk')
    assert v['duplicate'] == 1
    assert v['duplicate_of'] == '2025/FF4/Nuclear/nuclear protest'
    assert v['selected'] == 0, 'a duplicate must be deselected, not just badged'


def test_a_clip_sitting_on_disk_with_no_ledger_row_is_flagged(con, job, project_root):
    """The pre-ledger / hand-copied case. Nothing in the database knows about
    this file; the `[id]` in its name is the only evidence."""
    _touch(project_root / 'earlier search', 'Chan - T [abcdefghijk].mp4')
    db.add_video(con, job['id'], 'abcdefghijk', 'u')

    assert worker.mark_duplicates(con, job) == 1
    v = db.get_video(con, job['id'], 'abcdefghijk')
    assert v['duplicate'] == 1
    assert v['duplicate_of'] == f'{PROJECTS[0][1]}/earlier search'
    assert v['selected'] == 0


def test_the_ledger_wins_when_both_sources_have_it(con, job, project_root):
    """The ledger knows the project AND the term; the disk scan only knows a
    folder name in the project being searched."""
    _touch(project_root / 'earlier search', 'Chan - T [abcdefghijk].mp4')
    db.add_video(con, job['id'], 'abcdefghijk', 'u')
    db.ledger_add(con, 'abcdefghijk', 't', 'c', '2025-ff4-nuclear',
                  '2025/FF4/Nuclear', 'nuclear protest',
                  'Youtube/nuclear protest/y.mp4')
    worker.mark_duplicates(con, job)
    assert db.get_video(con, job['id'], 'abcdefghijk')['duplicate_of'] \
        == '2025/FF4/Nuclear/nuclear protest'


def test_a_new_clip_is_left_alone(con, job, project_root):
    db.add_video(con, job['id'], 'abcdefghijk', 'u')
    assert worker.mark_duplicates(con, job) == 0
    v = db.get_video(con, job['id'], 'abcdefghijk')
    assert v['duplicate'] == 0 and v['selected'] == 1


def test_the_scan_never_leaves_the_projects_root(con, job, monkeypatch):
    """The label comes from the dashboard database, but it still goes through
    safe_join -- a traversal in a project label must not scan /etc.

    YTDL-41 (2026-08-11): this used to add no video rows, so mark_duplicates
    returned 0 whatever happened -- deleting the safe_join call left it green
    while the worker rglobbed arbitrary host paths. The scan itself is watched
    now, and the refusal is asserted at its source.
    """
    scanned = []

    def spy(outdir):
        scanned.append(str(outdir))
        return {}

    monkeypatch.setattr(worker.ytsearch, 'existing_id_locations', spy)
    db.add_video(con, job['id'], 'abcdefghijk', 'u')

    evil = dict(job)
    evil['project_label'] = '../../../../etc'
    # A refusal, not a crash: the job carries on with an empty disk scan.
    assert worker.mark_duplicates(con, evil) == 0
    assert scanned == [], 'the traversal reached the filesystem scan'
    with pytest.raises(config.PathTraversalError):
        config.safe_join(config.PROJECTS_ROOT, evil['project_label'], 'Youtube')

    # ...and the same call with the real label DOES scan, so the assertion above
    # is not passing because nothing ever scans.
    assert worker.mark_duplicates(con, job) == 0
    assert len(scanned) == 1


def test_the_ledger_moves_rather_than_duplicating_on_a_re_download(con):
    db.ledger_add(con, 'abcdefghijk', 't', 'c', 'slug-a', 'A/One', 'term one',
                  'Youtube/term one/x.mp4', downloaded_by=USER)
    db.ledger_add(con, 'abcdefghijk', 't', 'c', 'slug-b', 'B/Two', 'term two',
                  'Youtube/term two/x.mp4', downloaded_by=USER)
    assert len(db.ledger_ids(con)) == 1
    assert db.ledger_get(con, 'abcdefghijk')['project_label'] == 'B/Two'


def test_the_download_folder_is_built_with_safe_join(job):
    outdir = config.safe_join(config.PROJECTS_ROOT, job['project_label'],
                              'Youtube', job['term_dir'])
    assert outdir.as_posix().endswith(
        f'{PROJECTS[0][1]}/Youtube/{job["term_dir"]}')
