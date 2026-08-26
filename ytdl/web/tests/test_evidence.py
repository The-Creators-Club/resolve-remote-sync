"""ytdl_evidence: what health reports instead of a configuration echo.

docs/YTDL_RESILIENCE_PLAN.md WP5 (2026-08-26). Two properties are worth a test
each: the evidence SURVIVES a container restart (the dashboard restarts for
reasons that have nothing to do with YouTube, and blank evidence reads exactly
like "nothing has been tried yet"), and NOTHING here can raise -- record() is
on the download path and snapshot() is on the health request path.
"""
import json

import pytest

from ytdlweb import ytdl_evidence


@pytest.fixture()
def evidence(tmp_path, monkeypatch):
    """Point the mirror at a tmp file and start from no evidence at all.

    The monkeypatch fixture is torn down AFTER this one, so the reset() below
    still resolves to the tmp path rather than deleting the real data root's
    file (which on a dev box is a real deployment's evidence).
    """
    path = tmp_path / 'ytdl_evidence.json'
    monkeypatch.setattr(ytdl_evidence, '_state_path', lambda: path)
    ytdl_evidence.reset()
    yield path
    ytdl_evidence.reset()


def _restart():
    """Everything a fresh container process starts with: empty memory, and the
    file still on the volume."""
    ytdl_evidence._last.clear()
    ytdl_evidence._loaded = False


def test_record_keeps_the_shape_health_publishes(evidence):
    ytdl_evidence.record(ytdl_evidence.PATH_ANONYMOUS, True, video_id='abc123')
    entry = ytdl_evidence.snapshot()[ytdl_evidence.PATH_ANONYMOUS]
    assert entry['ok'] is True
    assert entry['error'] == ''
    assert entry['video_id'] == 'abc123'
    assert entry['source'] == 'download'
    assert entry['at'] > 0


def test_record_persists_and_survives_a_restart(evidence):
    ytdl_evidence.record(ytdl_evidence.PATH_COOKIES, False,
                         error=RuntimeError('The page needs to be reloaded.'),
                         video_id='vid', source='canary')
    on_disk = json.loads(evidence.read_text(encoding='utf-8'))
    assert on_disk[ytdl_evidence.PATH_COOKIES]['ok'] is False

    _restart()
    entry = ytdl_evidence.snapshot()[ytdl_evidence.PATH_COOKIES]
    assert entry['ok'] is False
    assert 'needs to be reloaded' in entry['error']
    assert entry['source'] == 'canary'
    assert entry['video_id'] == 'vid'


def test_a_live_attempt_beats_the_file_it_has_not_written_yet(evidence):
    """The mirror can only ever FILL GAPS. Anything recorded in this process is
    newer than the file by construction, and a load that overwrote it would
    resurrect an outage the last download already disproved."""
    evidence.write_text(json.dumps({
        ytdl_evidence.PATH_ANONYMOUS: {'ok': False, 'error': 'old', 'at': 1,
                                       'video_id': '', 'source': 'download'}}),
        encoding='utf-8')
    _restart()
    ytdl_evidence.record(ytdl_evidence.PATH_ANONYMOUS, True, video_id='new')
    snap = ytdl_evidence.snapshot()
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['ok'] is True
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['video_id'] == 'new'


def test_a_garbage_mirror_is_no_evidence_not_an_exception(evidence):
    evidence.write_text('{not json at all', encoding='utf-8')
    _restart()
    assert ytdl_evidence.snapshot() == {}


def test_an_unwritable_data_root_costs_the_mirror_not_the_download(tmp_path,
                                                                  monkeypatch):
    """A bookkeeping failure must never propagate: record() is called from the
    download phase, where raising would fail a clip that actually worked."""
    blocker = tmp_path / 'not-a-dir'
    blocker.write_text('', encoding='utf-8')
    monkeypatch.setattr(ytdl_evidence, '_state_path',
                        lambda: blocker / 'sub' / 'ytdl_evidence.json')
    ytdl_evidence._last.clear()
    ytdl_evidence._loaded = True

    ytdl_evidence.record(ytdl_evidence.PATH_ANONYMOUS, True)     # must not raise
    assert ytdl_evidence.snapshot()[ytdl_evidence.PATH_ANONYMOUS]['ok'] is True
    ytdl_evidence._last.clear()


def test_snapshot_is_a_copy(evidence):
    ytdl_evidence.record(ytdl_evidence.PATH_ANONYMOUS, True)
    snap = ytdl_evidence.snapshot()
    snap[ytdl_evidence.PATH_ANONYMOUS]['ok'] = False
    assert ytdl_evidence.snapshot()[ytdl_evidence.PATH_ANONYMOUS]['ok'] is True


# ---------------------------------------------------------- the cookie jar

def test_cookie_jar_state_tells_configured_from_usable(tmp_path):
    """CR-80: the fix parked the flagged jar as its two Netscape header lines
    with YTDL_COOKIES_FILE still pointing at it. "A path is set" is not
    evidence there is a session to try."""
    assert ytdl_evidence.cookie_jar_state('') == ytdl_evidence.JAR_NONE
    assert ytdl_evidence.cookie_jar_state(
        str(tmp_path / 'absent.txt')) == ytdl_evidence.JAR_NONE

    header_only = tmp_path / 'empty.txt'
    header_only.write_text('# Netscape HTTP Cookie File\n# generated\n',
                           encoding='utf-8')
    assert ytdl_evidence.cookie_jar_state(str(header_only)) == ytdl_evidence.JAR_EMPTY

    real = tmp_path / 'jar.txt'
    real.write_text('# Netscape HTTP Cookie File\n'
                    '.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n',
                    encoding='utf-8')
    assert ytdl_evidence.cookie_jar_state(str(real)) == ytdl_evidence.JAR_PRESENT


def test_cookie_jar_of_anonymous_cookies_is_not_a_session(tmp_path):
    """Measured 2026-08-26: yt-dlp rewrote CR-80's parked jar with PREF, SOCS,
    YSC and VISITOR_INFO1_LIVE, and health called that `present`. A jar with no
    login cookie is not a path the worker may fall back to."""
    anon = tmp_path / 'anon.txt'
    anon.write_text('# Netscape HTTP Cookie File\n'
                    '.youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tf6=40000000\n'
                    '.youtube.com\tTRUE\t/\tTRUE\t1803271086\tVISITOR_INFO1_LIVE\tabc\n'
                    '.youtube.com\tTRUE\t/\tTRUE\t0\tYSC\txyz\n',
                    encoding='utf-8')
    assert ytdl_evidence.cookie_jar_state(str(anon)) == ytdl_evidence.JAR_ANONYMOUS

    signed = tmp_path / 'signed.txt'
    signed.write_text(anon.read_text(encoding='utf-8')
                      + '.youtube.com\tTRUE\t/\tTRUE\t1803271086\t__Secure-3PSID\tsecret\n',
                      encoding='utf-8')
    assert ytdl_evidence.cookie_jar_state(str(signed)) == ytdl_evidence.JAR_PRESENT
